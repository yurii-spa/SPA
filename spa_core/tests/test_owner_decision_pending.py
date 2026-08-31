"""Сторож «у остановки должен быть ЖИВОЙ вопрос владельцу» (цикл #195).

КАЖДЫЙ тест — положительный контроль реальной аварии **10.08.2026**:

    00:52 UTC  прод встал (`data/kill_switch_active.json`, threat_reactor: HALT);
    12:23 UTC  владельцу ушёл вопрос, которым остановку можно снять;
    13:30 UTC  книга всё ещё в кэше, deployed 0 %, а разрыв в 11.5 часов не
               измерял НИ ОДИН сторож.

Время здесь — ВХОД (`now=`), и отметки в фикстурах тоже фиксированные: обе стороны
закреплены, тест не протухнет от движения календаря (`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spa_core.monitoring.owner_decision_pending import (
    CRITICAL,
    OK,
    PENDING_CRITICAL_H,
    WARNING,
    check_pending_owner_decisions,
    run,
)

# FROZEN-DATE-OK: injected-clock — `now=` передаётся в КАЖДОМ вызове, и все
# отметки фикстур взяты из той же хронологии 10.08: обе стороны закреплены,
# движение календаря на вердикт не влияет вовсе (предпочтение №1
# `.claude/rules/deployment.md`). Сама дата здесь к тому же и предмет — это
# дословная хронология аварии, ради которой сторож написан.

# --- Хронология аварии 10.08 ------------------------------------------------
HALT_AT = "2026-08-10T00:52:40.835853+00:00"
PUSHED_AT = "2026-08-10T12:23:04.287867+00:00"
NOW_1330 = dt.datetime(2026, 8, 10, 13, 30, tzinfo=dt.timezone.utc)
NOW_0100 = dt.datetime(2026, 8, 10, 1, 0, tzinfo=dt.timezone.utc)

CARD_ID = "owner-decision-sistema-ostanovlena-avariinym-vyklyuchat"


@pytest.fixture()
def tree(tmp_path: Path):
    """Дерево-песочница: data/ и трекер рядом, как в настоящем репозитории."""
    data = tmp_path / "data"
    tracker = tmp_path / "nimbalyst-local" / "tracker"
    data.mkdir()
    tracker.mkdir(parents=True)
    return data, tracker


def _halt(data: Path, at: str = HALT_AT) -> None:
    (data / "kill_switch_active.json").write_text(json.dumps({
        "activated_at": at,
        "reason": "threat_reactor: emergency breaker: HALT",
        "source": "kill_switch_checker",
    }), encoding="utf-8")


def _journal(data: Path, pushes: list) -> None:
    (data / "telegram_owner_decisions.json").write_text(
        json.dumps({"schema_version": 1, "pushes": pushes}), encoding="utf-8")


def _card(tracker: Path, card_id: str = CARD_ID, status: str = "needs-owner") -> None:
    (tracker / f"{card_id}.md").write_text(
        "---\n"
        "trackerStatus:\n"
        "  type: owner-decision\n"
        f'title: "Система остановлена аварийным выключателем"\n'
        f"status: {status}\n"
        "---\n\n## Что от тебя нужно\n\n**Вариант 1 (рекомендую)** — снять.\n",
        encoding="utf-8")


def _push(*, card_id: str = CARD_ID, pushed_at: str = PUSHED_AT,
          buttons: bool = True, choice=None) -> dict:
    return {"pid": "8aeaeddb", "card_id": card_id, "card": f"/x/{card_id}.md",
            "title": "Система остановлена аварийным выключателем",
            "pushed_at": pushed_at, "buttons": buttons, "choice": choice}


# ===========================================================================
# H1 — ТУПИК: остановка есть, вопроса нет (00:52 → 01:00 живой аварии)
# ===========================================================================
def test_halt_without_any_question_is_a_dead_end(tree):
    data, tracker = tree
    _halt(data)
    _journal(data, [])

    doc = check_pending_owner_decisions(now=NOW_0100, data_dir=data, tracker_dir=tracker)

    assert doc["status"] == CRITICAL
    assert doc["halted"] is True
    assert doc["pending_count"] == 0
    assert "ТУПИК" in doc["issues"][0]
    assert "пути вверх нет" in doc["issues"][0]
    # Возраст простоя назван числом, а не «недавно».
    assert "0.1ч" in doc["issues"][0]


def test_dead_end_is_not_declared_when_the_queue_could_not_be_measured(tree):
    """«Не измерено» и «нет вопроса» — РАЗНЫЕ факты, и путать их нельзя.

    Тревога обязана быть, но поклёпа «вопроса не задано» — нет: журнал просто
    нечитаем. Это ровно та развилка, на которой fail-CLOSED вырождается в ложь.
    """
    data, tracker = tree
    _halt(data)
    (data / "telegram_owner_decisions.json").write_text("{не json", encoding="utf-8")

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["status"] == CRITICAL
    assert "НЕ ИЗМЕРЕНО" in doc["issues"][0]
    assert "ТУПИК" not in doc["issues"][0]
    assert doc["unchecked"] and doc["unchecked"][0]["check"] == "push_journal"


# ===========================================================================
# H2 — остановка ждёт ЧЕЛОВЕКА (авария 10.08 целиком)
# ===========================================================================
def test_halt_with_a_pending_question_names_the_wait_10_08(tree):
    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push()])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 1
    assert doc["halt_age_h"] == pytest.approx(12.62, abs=0.02)
    assert doc["oldest_pending_age_h"] == pytest.approx(1.12, abs=0.02)
    line = doc["issues"][0]
    assert "ОСТАНОВЛЕНА" in line and "ждёт ЧЕЛОВЕКА" in line
    # Оба срока в одной строке: простой И возраст вопроса — это разные величины,
    # и 10.08 они разошлись на 11.5 часа.
    assert "12.6ч" in line and "1.1ч" in line
    # Часы считает ПРОСТОЙ: вопрос свежий (1.1ч), но система стоит 12.6ч ⇒ CRITICAL.
    assert doc["status"] == CRITICAL


def test_a_fresh_halt_with_a_pending_question_is_only_a_warning(tree):
    """Контроль в обратную сторону: полтора часа простоя — ещё не тревога."""
    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push(pushed_at="2026-08-10T01:00:00+00:00")])

    doc = check_pending_owner_decisions(
        now=dt.datetime(2026, 8, 10, 2, 22, tzinfo=dt.timezone.utc),
        data_dir=data, tracker_dir=tracker)

    assert doc["status"] == WARNING
    assert doc["halt_age_h"] < PENDING_CRITICAL_H


def test_the_clock_is_the_standstill_not_the_freshness_of_the_question(tree):
    """Вопрос, заданный минуту назад, НЕ делает суточный простой свежим.

    Мутация, которую тест ловит: считать возраст по `oldest_pending_age_h`.
    Тогда достаточно переспросить владельца — и тревога гаснет, а книга стоит.
    """
    data, tracker = tree
    _halt(data, at="2026-08-09T00:52:40+00:00")          # простой ~36ч
    _card(tracker)
    _journal(data, [_push(pushed_at="2026-08-10T13:00:00+00:00")])  # вопрос 0.5ч

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["oldest_pending_age_h"] < PENDING_CRITICAL_H
    assert doc["halt_age_h"] > PENDING_CRITICAL_H
    assert doc["status"] == CRITICAL


# ===========================================================================
# Что НЕ является находкой (контроль в обратную сторону)
# ===========================================================================
def test_a_card_closed_after_the_button_is_not_pending(tree):
    """Ответ получен И доехал до очереди ⇒ ждущих вопросов нет.

    Это ПРЕЖНИЙ `test_answered_question_is_not_pending`, приведённый к тому, как
    ответ выглядит в жизни: нажатие владельца закрывает карточку (ADR-069/075),
    поэтому «отвечено» видно в очереди, а не только в журнале. Прежняя фикстура
    держала карточку в `needs-owner` и одновременно объявляла вопрос отвеченным —
    в проде такого состояния не бывает, а если оно случится, то это НАХОДКА
    (ответ не доехал), и её проверяет соседний тест ниже. Изменение теста
    намеренное (инв. #16): проверка не ослаблена, а разделена надвое —
    зафиксированы ОБА исхода, и «не ждём» теперь якорится на очереди, которая
    и есть источник правды с цикла #199.
    """
    data, tracker = tree
    _halt(data)
    _card(tracker, status="ingested")
    _journal(data, [_push(choice="1")])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0
    # Спросить больше нечего, а выключатель активен ⇒ ТУПИК, а не «ждёт человека».
    assert "ТУПИК" in doc["issues"][0]


def test_an_answer_that_never_reached_the_queue_is_named_not_dropped(tree):
    """Нажатие есть, а карточка всё ещё ждёт владельца — расхождение НАЗЫВАЕТСЯ.

    Мутация, которую тест ловит: считать журнал главнее очереди («есть choice ⇒
    не ждём»). Тогда неинжестированный ответ гасит вопрос молча — ровно так
    10.08 четыре ответа владельца лежали, не доехав до очереди.
    """
    data, tracker = tree
    _card(tracker)                                   # карточка ВСЁ ЕЩЁ needs-owner
    _journal(data, [_push(choice="1")])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 1                 # очередь главнее журнала
    assert doc["answered_but_open_count"] == 1
    assert doc["status"] == WARNING
    assert any("не доехал до очереди" in line for line in doc["issues"])


def test_a_question_re_asked_after_an_answer_is_waiting_not_an_anomaly(tree):
    """Судим по СВЕЖЕЙ отправке, а не по любой из бывших.

    Переспросить владельца — законный ход (#198 так переотправлял `own-33`,
    починив кнопки). Если считать «ответ был когда-то» вечной находкой, каждый
    переспрос порождал бы жалобу на уже сделанное — шум, который учат пролистывать.
    """
    data, tracker = tree
    _card(tracker)
    _journal(data, [_push(choice="1", pushed_at="2026-08-10T09:00:00+00:00"),
                    _push(pushed_at="2026-08-10T12:23:04+00:00")])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 1 and doc["delivered_count"] == 1
    assert doc["answered_but_open_count"] == 0
    assert doc["oldest_pending_age_h"] == pytest.approx(1.12, abs=0.02)   # по свежей
    assert doc["status"] == OK


def test_card_closed_outside_the_button_is_not_pending(tree):
    """Владелец мог ответить и в карточке — статус карточки главнее журнала."""
    data, tracker = tree
    _card(tracker, status="owner-done")
    _journal(data, [_push()])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0
    assert doc["status"] == OK


def test_pending_questions_without_a_halt_are_fields_not_an_alarm(tree):
    """Владелец в отъезде — WARN, который не может погаснуть 9 дней, это шум.

    Тревога поднимается там, где ожидание СТОИТ трека, то есть при остановке.
    """
    data, tracker = tree
    _card(tracker)
    _journal(data, [_push()])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["halted"] is False
    assert doc["pending_count"] == 1
    assert doc["status"] == OK
    assert doc["issues"] == []


# ===========================================================================
# H3 — вопрос, на который владелец физически не может ответить
# ===========================================================================
def test_a_pending_question_without_buttons_is_named(tree):
    data, tracker = tree
    _card(tracker)
    _journal(data, [_push(buttons=False)])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["buttonless_count"] == 1
    assert doc["status"] == WARNING
    assert "БЕЗ КНОПОК" in doc["issues"][0]


def test_the_buttonless_finding_names_its_cause_not_just_the_card(tree):
    """Авария 21.08 (#332): «БЕЗ КНОПОК» три цикла подряд не говорило НИЧЕГО.

    Причин у этого состояния минимум четыре, лечатся они по-разному, и с одного
    взгляда неразличимы: карточку-задание из-за этого написали с ОДНОЙ гипотезой
    на два вопроса, и обе причины оказались другими. Причина обязана стоять в
    самой находке — и машинно, и словами.
    """
    data, tracker = tree
    _card(tracker)
    _journal(data, [_push(buttons=False)])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    entry = doc["pending"][0]
    reason = entry["buttons_reason"]
    assert reason["code"], "у находки обязан быть машинный код причины"
    assert reason["text"] and reason["remedy"]
    assert reason["code"] in doc["issues"][0], "код причины обязан стоять В строке находки"
    assert reason["text"][:40] in doc["issues"][0]


def test_a_question_that_did_get_buttons_is_not_diagnosed(tree):
    """Обратный контроль: у здорового вопроса причины нет — и мерить её незачем.

    Сверка стоит процесса git; гонять её по всей очереди значило бы платить за
    вопрос, с которым всё в порядке.
    """
    data, tracker = tree
    _card(tracker)
    _journal(data, [_push(buttons=True)])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["buttonless_count"] == 0
    assert "buttons_reason" not in doc["pending"][0]


def test_options_living_only_on_origin_reach_the_report_as_a_stale_tree(tmp_path):
    """Сквозной повтор `own-33`: варианты есть на `origin/main` и нет в дереве.

    Ровно эта причина не видна с диска НИКАК, и ровно её сторож не спрашивал.
    Фикстура — настоящий git-репозиторий: проверяется ЭФФЕКТ, а не заглушка.
    """
    import subprocess

    root = tmp_path / "repo"
    data = root / "data"
    tracker = root / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)
    data.mkdir(parents=True)

    def git(*args):
        res = subprocess.run(["git", "-C", str(root), *args],
                             capture_output=True, text=True)
        assert res.returncode == 0, f"git {args}: {res.stderr}"
        return res.stdout

    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "test")

    _card(tracker)                                   # версия С вариантами
    git("add", "-A")
    git("commit", "-q", "-m", "c")
    git("update-ref", "refs/remotes/origin/main", "HEAD")

    # …а в дереве карточка отстала: тот же вопрос прозой, без единого варианта.
    (tracker / f"{CARD_ID}.md").write_text(
        "---\ntrackerStatus:\n  type: owner-decision\n"
        'title: "Система остановлена аварийным выключателем"\n'
        "status: needs-owner\n---\n\n## Что от тебя нужно\n\nСними стоп-кран.\n",
        encoding="utf-8")
    _journal(data, [_push(buttons=False)])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    reason = doc["pending"][0]["buttons_reason"]
    assert reason["code"] == "card_stale_vs_origin", reason["text"]
    assert reason["measured"] is True
    # НАМЕРЕННАЯ правка утверждения (цикл #439, инвариант #16): проверялось
    # `doc["issues"][0]`, то есть ПОРЯДОК, а не предмет. Порядок сместился по верной
    # причине: эта же фикстура — живой пример находки, которую сторож раньше не видел
    # вовсе (на origin вопрос `needs-owner`, в дереве ДРУГОЙ текст), и H8 теперь о ней
    # говорит. Утверждение не ослаблено, а РАСШИРЕНО: предмет по-прежнему обязан
    # доехать до отчёта, и вдобавок обязана появиться новая находка о том же файле.
    assert any("card_stale_vs_origin" in i for i in doc["issues"]), doc["issues"]
    assert any("до владельца из этого дерева НЕ доходят" in i for i in doc["issues"]), \
        doc["issues"]
    assert any("в дереве ДРУГОЙ текст" in i for i in doc["issues"]), doc["issues"]


def test_halt_line_comes_first_even_when_buttons_are_missing_too(tree):
    """`reason` отчёта — это issues[0]; первой строкой обязана быть ОСТАНОВКА."""
    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push(buttons=False)])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert "ОСТАНОВЛЕНА" in doc["reason"]
    assert any("БЕЗ КНОПОК" in line for line in doc["issues"])


# ===========================================================================
# Fail-CLOSED на карточке, которой нет в живом дереве (авария #194)
# ===========================================================================
def test_a_push_whose_card_is_missing_is_unchecked_not_silently_dropped(tree):
    """Нажатие по такой карточке отвечает «карточка исчезла» — молчать нельзя."""
    data, tracker = tree
    _journal(data, [_push()])          # карточки в трекере НЕТ

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0
    assert doc["unchecked"] and doc["unchecked"][0]["check"] == f"card_missing:{CARD_ID}"
    assert doc["status"] == WARNING    # без остановки — предупреждение
    # А во время остановки та же неизмеримость обязана быть CRITICAL.
    _halt(data)
    doc2 = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)
    assert doc2["status"] == CRITICAL


def test_an_unreadable_card_is_unchecked_not_treated_as_closed(tree):
    """Пустой статус сравнился бы с `needs-owner` как «не равно» — и вопрос молча
    выпал бы из очереди. Это fail-OPEN ровно того вида, ради которого модуль и писан.
    """
    data, tracker = tree
    _halt(data)
    (tracker / f"{CARD_ID}.md").write_text("вообще не карточка", encoding="utf-8")
    _journal(data, [_push()])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0
    assert any(u["check"] == f"card_unreadable:{CARD_ID}" for u in doc["unchecked"])
    assert doc["status"] == CRITICAL
    assert "НЕ ИЗМЕРЕНО" in doc["issues"][0] and "ТУПИК" not in doc["issues"][0]


def test_an_absent_journal_is_not_a_finding_but_a_corrupt_one_is(tree):
    """«Файла нет» ≠ «файл испорчен».

    Чистое дерево (CI, песочница) журнала отправок не имеет — там владельцу просто
    ничего не отправляли, и предупреждение здесь было бы шумом, который учат
    пролистывать. А ВОТ испорченный журнал делает очередь вопросов неизмеримой.
    """
    data, tracker = tree

    absent = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)
    assert absent["status"] == OK
    assert absent["journal_present"] is False
    assert absent["unchecked"] == []

    (data / "telegram_owner_decisions.json").write_text("{не json", encoding="utf-8")
    corrupt = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)
    assert corrupt["status"] == WARNING
    assert corrupt["unchecked"][0]["check"] == "push_journal"


def test_a_halt_with_no_journal_at_all_is_still_a_dead_end(tree):
    """Отсутствие журнала гасит шум, но НЕ гасит тревогу об остановке.

    Мутация, которую тест ловит: «нет журнала ⇒ молчим» целиком. Тогда самая
    страшная конфигурация — стоим и никого не спросили — стала бы тихой.
    """
    data, tracker = tree
    _halt(data)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["status"] == CRITICAL
    assert "ТУПИК" in doc["issues"][0]


# ===========================================================================
# H4 — вопрос ЕСТЬ В ОЧЕРЕДИ, а доставки нет (замер 10.08, цикл #198)
#
# Каждый тест ниже — положительный контроль второго замера того же дня:
#     очередь на origin/main держит ПЯТЬ карточек `needs-owner`,
#     сторож называет ТРИ, а `own-33`/`own-34` владелец не получал НИКОГДА.
# На модуле до #199 (список строился обходом журнала отправок) все они краснеют.
# ===========================================================================
QUEUE_5 = [
    "own-rnd-killswitch-rearm-policy-missing",
    "own-rnd-killswitch-soft-tier-meaning",
    "owner-decision-dva-dnya-treka-pomecheny-dokazannymi-hot",
    "own-33-plist-marker-for-cycle-origin",          # отправлена не была
    "own-34-kill-switch-active-13h-unnoticed",       # отправлена не была
]
DELIVERED_3 = QUEUE_5[:3]


def _queue_of_five(tracker: Path, data: Path) -> None:
    for card_id in QUEUE_5:
        _card(tracker, card_id=card_id)
    _journal(data, [_push(card_id=c, pushed_at="2026-08-10T12:23:04+00:00")
                    for c in DELIVERED_3])


def test_the_queue_is_the_source_not_the_journal_10_08(tree):
    """Пять в очереди — пять и в отчёте; трое отправлены, двое НЕТ."""
    data, tracker = tree
    _queue_of_five(tracker, data)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 5          # до #199 здесь стояло 3
    assert doc["delivered_count"] == 3
    assert doc["undelivered_count"] == 2
    lost = {p["card_id"] for p in doc["pending"] if not p["delivered"]}
    assert lost == {"own-33-plist-marker-for-cycle-origin",
                    "own-34-kill-switch-active-13h-unnoticed"}


def test_an_undelivered_question_is_named_out_loud_even_without_a_halt(tree):
    """Не «владелец молчит» (шум на 9 дней отъезда), а НАШЕ упущение.

    Гасится одной отправкой, поэтому предупреждение здесь честное и стираемое —
    в отличие от вечного WARN, который учат пролистывать.
    """
    data, tracker = tree
    _queue_of_five(tracker, data)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["halted"] is False
    assert doc["status"] == WARNING
    line = next(l for l in doc["issues"] if "НЕ ОТПРАВЛЕНЫ" in l)
    assert "2 из 5" in line
    # Имена названы: без них находка нечитаема — искать в 5 карточках вручную.
    assert "own-33-plist-marker-for-cycle-origin" in line
    # И в `reason` — это его печатает шаг 0-офис — потеря видна БЕЗ раскрытия
    # отчёта: до #199 там стояло «остановки нет; вопросов без ответа: 3».
    assert "НЕ ОТПРАВЛЕНЫ" in doc["reason"] and "2 из 5" in doc["reason"]


def test_a_halt_whose_only_question_was_never_sent_is_a_dead_end_in_practice(tree):
    """Худший случай: стоим, вопрос заведён — и владелец о нём не знает.

    От «вопроса не задано» (ТУПИК) отличается тем, ГДЕ оборвался путь вверх,
    и это различие обязано звучать: иначе чинить будут не то место.
    """
    data, tracker = tree
    _halt(data)
    _card(tracker)                                   # в очереди есть
    _journal(data, [])                               # отправок нет ни одной

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["status"] == CRITICAL
    assert doc["pending_count"] == 1 and doc["undelivered_count"] == 1
    first = doc["issues"][0]
    assert "ОСТАНОВЛЕНА" in first and "НИ ОДИН НЕ ОТПРАВЛЕН" in first
    assert "только на бумаге" in first
    # Поклёпа «вопроса не задано» нет — вопрос-то есть.
    assert "НЕ ЗАДАНО НИ ОДНОГО" not in first
    # И это ОДНА строка, а не две про одно и то же.
    assert sum("НЕ ОТПРАВЛЕН" in l.upper() for l in doc["issues"]) == 1


def test_during_a_halt_an_undelivered_question_outranks_a_warning(tree):
    """Есть и доставленный вопрос, и потерянный: строка про остановку первая,
    потеря названа отдельно, степень — CRITICAL (владелец физически заперт)."""
    data, tracker = tree
    _halt(data, at="2026-08-10T13:00:00+00:00")      # простой 0.5ч ⇒ сам по себе WARN
    _card(tracker)
    _card(tracker, card_id="own-34-kill-switch-active-13h-unnoticed")
    _journal(data, [_push(pushed_at="2026-08-10T13:05:00+00:00")])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert "ОСТАНОВЛЕНА" in doc["issues"][0] and "ждёт ЧЕЛОВЕКА" in doc["issues"][0]
    # Отправлен ОДИН из двух — число в строке про остановку это ЗНАЕТ.
    assert "отправлено 1 вопрос" in doc["issues"][0]
    assert any("НЕ ОТПРАВЛЕНЫ" in l for l in doc["issues"])
    assert doc["status"] == CRITICAL


def test_an_undelivered_question_is_neither_buttonless_nor_aged(tree):
    """Неотправленный вопрос не выдаётся ни за «ушёл без кнопок», ни за молчание
    владельца: у него нет ни отправки, ни возраста ожидания — и придумывать их
    нельзя (иначе одна потеря считается трижды и тонет в шуме)."""
    data, tracker = tree
    _card(tracker)                                   # только очередь, журнала нет

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["buttonless_count"] == 0
    assert doc["oldest_pending_age_h"] is None
    assert doc["pending"][0]["age_h"] is None and doc["pending"][0]["delivered"] is False
    assert sum(1 for l in doc["issues"] if "own-" in l or "owner-decision-" in l) == 1


# ===========================================================================
# Fail-CLOSED и НЕ-находки на стороне очереди
# ===========================================================================
def test_an_owner_card_without_a_status_is_unchecked_not_invisible(tree):
    """Карточка без `status:` невидима ЛЮБОМУ фильтру — в т.ч. очереди владельца.

    Молча пропустить её значило бы вернуть то самое слепое пятно, только с
    другой стороны.
    """
    data, tracker = tree
    (tracker / "own-35-bez-statusa.md").write_text(
        "---\ntrackerStatus:\n  type: owner-decision\ntitle: \"Вопрос\"\n---\n\nтело\n",
        encoding="utf-8")

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0
    assert any(u["check"] == "queue_card_status_missing:own-35-bez-statusa"
               for u in doc["unchecked"])
    assert doc["status"] == WARNING


def test_foreign_files_in_the_tracker_are_not_dragged_into_unchecked(tree):
    """Контроль в обратную сторону: доска и чужие карточки — не вопросы владельцу.

    Нестираемое «не измерено» морит очередь голодом ровно так же, как молчание,
    поэтому чужие файлы в находки не тянем.
    """
    data, tracker = tree
    (tracker / "_BOARD.md").write_text("# доска\n\nне карточка вовсе\n", encoding="utf-8")
    (tracker / "inbox-kakaya-to-zadacha.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\ntitle: \"Задача\"\nstatus: new\n---\n\nтело\n",
        encoding="utf-8")
    _card(tracker)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 1
    assert doc["unchecked"] == []


def test_an_absent_tracker_dir_is_not_a_finding(tree):
    """Песочница/чистая установка без очереди — законное состояние, а не авария.

    Тревога об остановке при этом НЕ гаснет (контроль ниже).
    """
    data, _tracker = tree
    absent = data.parent / "net-takogo-kataloga"

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=absent)
    assert doc["status"] == OK
    assert doc["queue_present"] is False and doc["unchecked"] == []

    _halt(data)
    halted = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=absent)
    assert halted["status"] == CRITICAL and "ТУПИК" in halted["issues"][0]


# ===========================================================================
# Артефакт: без файла обязательного читателя (шаг 0-офис) не существует
# ===========================================================================
def test_run_writes_the_artifact_next_to_the_data_dir(tree):
    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push()])

    doc, path = run(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert path == data / "owner_decision_pending.json"
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["status"] == doc["status"] == CRITICAL
    assert written["generated_at"] == NOW_1330.isoformat()


# ===========================================================================
# Проводка: пульс флота обязан НЕСТИ эту находку, а не только модуль
# ===========================================================================
def test_agent_health_carries_the_finding(tree, monkeypatch):
    """Мутация «снять проводку» обязана краснить: без неё модуль — сирота.

    Именно так умирал класс #144: правка детали при мёртвой проводке зелена и
    бесполезна.
    """
    from spa_core.monitoring import agent_health_monitor as ahm

    data, tracker = tree
    _halt(data)
    _card(tracker)
    _journal(data, [_push()])

    checks, status, issues = ahm.check_system(data, NOW_1330)

    assert checks["owner_pending_count"] == 1
    assert checks["owner_pending_oldest_h"] == pytest.approx(1.12, abs=0.02)
    assert status == ahm.CRITICAL
    assert any("ждёт ЧЕЛОВЕКА" in line for line in issues)


def test_agent_health_carries_the_lost_question_too(tree, monkeypatch):
    """Пульс флота обязан нести И потерю доставки, а не только ожидание ответа.

    `checks["owner_pending_count"]` читают как «сколько вопросов ждут владельца»;
    до #199 там стояло число из журнала отправок, и потерянный вопрос не попадал
    ни в счётчик, ни в строки. Мутация «вернуть источником журнал» краснит здесь.
    """
    from spa_core.monitoring import agent_health_monitor as ahm

    data, tracker = tree
    _queue_of_five(tracker, data)

    checks, status, issues = ahm.check_system(data, NOW_1330)

    assert checks["owner_pending_count"] == 5
    assert status in (ahm.WARNING, ahm.CRITICAL)
    assert any("НЕ ОТПРАВЛЕНЫ" in line for line in issues)


def test_agent_health_reports_unchecked_when_the_probe_itself_fails(tree, monkeypatch):
    """Упавшая проверка — это НЕ «путь вверх есть» (fail-CLOSED на самой себе)."""
    from spa_core.monitoring import agent_health_monitor as ahm
    from spa_core.monitoring import owner_decision_pending as odp

    data, _tracker = tree

    def _boom(**_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(odp, "check_pending_owner_decisions", _boom)
    _checks, status, issues = ahm.check_system(data, NOW_1330)

    assert status in (ahm.WARNING, ahm.CRITICAL)
    assert any("owner_decision_pending UNCHECKED" in line for line in issues)


# ===========================================================================
# H6 — ФАНТОМ: карточка в очереди, которую владельцу никто не задавал
# ===========================================================================
# Положительный контроль аварии 11.08.2026: `ask_router` отдавал падение headless
# `claude` как обычный вердикт `("unclear", …)`, интейк исполнял его как вердикт и
# выпустил 44 карточки «Уточнение по заметке: …». ЭТОТ сторож тогда доложил «44 из 48
# вопросов владельцу не отправлены» — правду о карточках и неправду о владельце,
# которому ни один из 44 вопросов не был нужен. Теперь класс узнаётся по подписи.

_OUTAGE_TEXT = "Не смог обработать сообщение. Переформулируй или пришли как /task <текст>."


def _phantom(tracker: Path, card_id: str, *, asked: str = _OUTAGE_TEXT,
             source: str = "intake", title: str = "Уточнение по заметке: ADR-070.2") -> None:
    (tracker / f"{card_id}.md").write_text(
        "---\n"
        "trackerStatus:\n  type: owner-decision\n"
        f'title: "{title}"\n'
        "status: needs-owner\n"
        f"source: {source}\n"
        "created: 2026-08-11\n"
        "---\n\n"
        "## Что случилось и почему это важно\nПришло сообщение, непонятно.\n\n"
        f"## Что от тебя нужно\n{asked}\n",
        encoding="utf-8")


def test_phantom_cards_are_not_counted_as_owner_questions(tree):
    """44 следа упавшего классификатора — это НЕ очередь владельца."""
    data, tracker = tree
    for i in range(3):
        _phantom(tracker, f"owner-decision-utochnenie-po-zametke-{i}")

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0, "фантомы попали в счёт вопросов владельцу"
    assert doc["undelivered_count"] == 0, (
        "фантомы выданы за неотправленные вопросы — ровно эта строка и обманула 11.08")
    assert doc["phantom_count"] == 3


def test_phantom_cards_are_named_with_their_remedy(tree):
    """Молчать о них тоже нельзя: очередь засорена, и лекарство должно быть названо."""
    data, tracker = tree
    _phantom(tracker, "owner-decision-utochnenie-po-zametke-0")

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    joined = "\n".join(doc["issues"])
    assert "упавшего классификатора" in joined
    assert "scripts/repair_phantom_intake_cards.py" in joined
    assert doc["status"] == WARNING


def test_a_real_question_next_to_phantoms_is_still_counted(tree):
    """Главный риск починки: заодно потерять НАСТОЯЩИЙ вопрос владельца."""
    data, tracker = tree
    _card(tracker)                                   # настоящий вопрос
    for i in range(5):
        _phantom(tracker, f"owner-decision-utochnenie-po-zametke-{i}")

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 1
    assert [p["card_id"] for p in doc["pending"]] == [CARD_ID]
    assert doc["phantom_count"] == 5


def test_an_intake_card_with_a_real_question_is_not_a_phantom(tree):
    """Живой классификатор, сказавший UNCLEAR, задаёт НАСТОЯЩИЙ вопрос — он не фантом."""
    data, tracker = tree
    _phantom(tracker, "owner-decision-utochnenie-po-zametke-0",
             asked="Это про сайт или про агентов?")

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["phantom_count"] == 0
    assert doc["pending_count"] == 1


def test_a_handwritten_card_quoting_the_outage_text_is_not_a_phantom(tree):
    """Признак — СОВОКУПНОСТЬ: карточка не от интейка не становится фантомом от цитаты."""
    data, tracker = tree
    _phantom(tracker, "own-40-pro-avariyu", source="nimbalyst",
             title="Что делать с упавшим классификатором")

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["phantom_count"] == 0
    assert doc["pending_count"] == 1


# ===========================================================================
# H8 — очередь ЭТОГО дерева неполна (авария 17.08.2026, цикл #270)
#
# Прод-дерево держало 416 карточек, `origin/main` — 481. Среди 109 невидимых
# дереву карточек лежал живой вопрос владельцу `own-34` (`needs-owner`), и
# сторож доложил `undelivered_count: 0` — правда про КАТАЛОГ и неправда про
# ОЧЕРЕДЬ. Дальше — тот же самоподдерживающийся круг, что #199 закрыл этажом
# ниже: не синкнуто ⇒ нет файла ⇒ не в очереди ⇒ никто не заметил.
#
# Фикстуры здесь — настоящие крошечные git-репозитории: проверяется ЭФФЕКТ,
# а не подменённая заглушка. Дат в них нет — вердикт H8 от календаря не зависит.
# ===========================================================================
import subprocess  # noqa: E402 — рядом с тем, что его использует

from spa_core.owner_queue.origin_view import TRACKER_REL  # noqa: E402

_REF = "main"


def _git(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture()
def git_tree(tmp_path: Path):
    """Дерево-песочница ВНУТРИ репозитория: `data/` и очередь рядом, как в проде."""
    root = tmp_path / "repo"
    tracker = root / TRACKER_REL
    data = root / "data"
    tracker.mkdir(parents=True)
    data.mkdir()
    _git(tmp_path, "init", "-q", "-b", _REF, str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "test")
    return root, data, tracker


def _commit_and_hide(root: Path, tracker: Path, card_id: str) -> None:
    """Зафиксировать карточку на ref и убрать её файл — ровно состояние прода 17.08."""
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "queue")
    (tracker / f"{card_id}.md").unlink()


def test_a_question_living_only_on_the_ref_is_named_not_counted_as_absent(git_tree,
                                                                          monkeypatch):
    """Ядро аварии: `own-34` есть на ref, файла в дереве нет — молчать нельзя."""
    root, data, tracker = git_tree
    _card(tracker, card_id="own-34-kill-switch-active-13h-unnoticed")
    _journal(data, [])
    _commit_and_hide(root, tracker, "own-34-kill-switch-active-13h-unnoticed")
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["queue_gap_count"] == 1
    assert doc["origin_queue"]["measured"] is True
    assert doc["origin_queue"]["hidden"][0]["card_id"] == "own-34-kill-switch-active-13h-unnoticed"
    assert doc["origin_queue"]["hidden"][0]["delivered"] is False
    assert doc["status"] == WARNING
    gap_line = next(i for i in doc["issues"] if "НЕПОЛНА" in i)
    assert "own-34-kill-switch-active-13h-unnoticed" in gap_line
    assert "НИ РАЗУ не отправлены владельцу: 1" in gap_line


def test_the_defect_is_that_the_tree_counters_stay_green(git_tree, monkeypatch):
    """То, что делало аварию невидимой: счётчики дерева на такую карточку не реагируют.

    Это не жалоба на счётчики — они честны про свой каталог. Тест закрепляет, что
    зелёное число теперь СОСЕДСТВУЕТ с находкой, а не заменяет её.
    """
    root, data, tracker = git_tree
    _card(tracker, card_id="own-34-kill-switch-active-13h-unnoticed")
    _journal(data, [])
    _commit_and_hide(root, tracker, "own-34-kill-switch-active-13h-unnoticed")
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["pending_count"] == 0 and doc["undelivered_count"] == 0
    assert doc["status"] != OK, "зелёный статус при потерянном вопросе и есть авария 17.08"
    assert "НЕПОЛНА" in doc["reason"]


#: Отправка ДО среза NOW_0100 — иначе возраст ожидания вышел бы отрицательным.
PUSHED_0055 = "2026-08-10T00:55:00+00:00"


def _halted_with_one_answered_question(root: Path, data: Path, tracker: Path) -> None:
    """Остановка свежая (0.1ч) и вопрос владельцу ОТПРАВЛЕН ⇒ сама по себе WARNING.

    Ровно та расстановка, в которой видно вклад H8 и ничей больше: не будь её,
    остановка дала бы CRITICAL своей веткой «тупик», и тест закрепил бы не то,
    что утверждает.
    """
    _halt(data)
    _card(tracker)
    _journal(data, [_push(pushed_at=PUSHED_0055)])
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "queue")


def test_a_halt_with_an_answered_question_is_only_a_warning_by_itself(git_tree,
                                                                      monkeypatch):
    """Обратный контроль к следующему тесту: без невидимой карточки — WARNING."""
    root, data, tracker = git_tree
    _halted_with_one_answered_question(root, data, tracker)
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_0100, data_dir=data, tracker_dir=tracker)

    assert doc["queue_gap_count"] == 0
    assert doc["status"] == WARNING


def test_the_lost_way_up_turns_that_halt_critical(git_tree, monkeypatch):
    """Во время остановки невидимый путь вверх не лучше отсутствующего.

    К расстановке выше добавлен ОДИН невидимый дереву вопрос — и только он
    двигает вердикт WARNING → CRITICAL.
    """
    root, data, tracker = git_tree
    _card(tracker, card_id="own-34-kill-switch-active-13h-unnoticed")
    _halted_with_one_answered_question(root, data, tracker)
    (tracker / "own-34-kill-switch-active-13h-unnoticed.md").unlink()
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_0100, data_dir=data, tracker_dir=tracker)

    assert doc["queue_gap_count"] == 1
    assert doc["status"] == CRITICAL
    assert any("НЕПОЛНА" in i for i in doc["issues"])


def test_the_lost_way_up_is_named_during_a_dead_end_halt_too(git_tree, monkeypatch):
    """Тупик остаётся тупиком, но причина обрыва пути вверх обязана прозвучать."""
    root, data, tracker = git_tree
    _halt(data)
    _card(tracker, card_id="own-34-kill-switch-active-13h-unnoticed")
    _journal(data, [])
    _commit_and_hide(root, tracker, "own-34-kill-switch-active-13h-unnoticed")
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["status"] == CRITICAL
    assert "ТУПИК" in doc["issues"][0], "остановка обязана оставаться первой строкой"
    assert any("НЕПОЛНА" in i for i in doc["issues"])


def test_a_complete_queue_says_zero_and_stays_green(git_tree, monkeypatch):
    """Обратный контроль: синхронное дерево не должно рождать вечную находку."""
    root, data, tracker = git_tree
    _card(tracker, card_id="own-40-otvechennyi", status="owner-done")
    _journal(data, [])
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "queue")
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["queue_gap_count"] == 0
    assert doc["origin_queue"]["measured"] is True
    assert doc["status"] == OK
    assert not any("НЕПОЛНА" in i for i in doc["issues"])


def test_a_hidden_card_that_is_not_an_owner_question_is_not_dragged_in(git_tree,
                                                                       monkeypatch):
    """Задание и закрытый вопрос — не вопросы владельцу; завышать очередь тоже нельзя."""
    root, data, tracker = git_tree
    (tracker / "inbox-zadanie.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\ntitle: \"задание\"\nstatus: new\n---\n\nx\n",
        encoding="utf-8")
    _card(tracker, card_id="own-41-zakryt", status="owner-done")
    _journal(data, [])
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "queue")
    (tracker / "inbox-zadanie.md").unlink()
    (tracker / "own-41-zakryt.md").unlink()
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["queue_gap_count"] == 0
    assert doc["status"] == OK


def test_a_hidden_question_that_was_sent_is_told_apart_from_one_never_sent(git_tree,
                                                                           monkeypatch):
    """Журнал отправок живёт в `data/` и с деревом не расходится — им и судим."""
    root, data, tracker = git_tree
    _card(tracker, card_id="own-34-kill-switch-active-13h-unnoticed")
    _journal(data, [_push(card_id="own-34-kill-switch-active-13h-unnoticed")])
    _commit_and_hide(root, tracker, "own-34-kill-switch-active-13h-unnoticed")
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["origin_queue"]["hidden"][0]["delivered"] is True
    gap_line = next(i for i in doc["issues"] if "НЕПОЛНА" in i)
    assert "НИ РАЗУ" not in gap_line, "отправленный вопрос нельзя объявлять неотправленным"


def test_an_unmeasurable_ref_is_said_out_loud_not_treated_as_a_full_queue(tree):
    """Песочница вне git: «сверять не с чем» ≠ «дереву видно всё».

    Статус СОЗНАТЕЛЬНО не поднимается: нет репозитория — законное состояние CI,
    песочницы и чистой установки, а нестираемое «не измерено» морит очередь
    голодом ровно так же, как молчание. Зато оговорка попадает в `reason`,
    который читает шаг 0-офис.
    """
    data, tracker = tree
    _card(tracker)
    _journal(data, [_push()])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["queue_gap_count"] is None, "None и 0 обязаны быть различимы"
    assert doc["origin_queue"]["measured"] is False
    assert doc["origin_queue"]["reason"]
    assert "полнота очереди НЕ ИЗМЕРЕНА" in doc["reason"]
    assert doc["status"] == OK


def test_a_broken_ref_never_pretends_the_queue_is_complete(git_tree, monkeypatch):
    """Ref не разрешается ⇒ «не измерено» с причиной, а не пустой список находок."""
    root, data, tracker = git_tree
    _card(tracker)
    _journal(data, [])
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "queue")
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF",
                        "origin/never-fetched")

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["queue_gap_count"] is None
    assert doc["origin_queue"]["measured"] is False
    assert "не разрешается" in doc["origin_queue"]["reason"]


def test_the_office_step_prints_the_gap_rather_than_truncating_it(git_tree, monkeypatch):
    """Читатель обязателен: находка без читателя — не находка.

    `reason` в шаге 0-офис обрезается до 160 символов, а идентификаторы карточек
    стоят в его хвосте. Поэтому у полноты очереди — своя строка.
    """
    import sys

    root, data, tracker = git_tree
    _card(tracker, card_id="own-34-kill-switch-active-13h-unnoticed")
    _journal(data, [])
    _commit_and_hide(root, tracker, "own-34-kill-switch-active-13h-unnoticed")
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)
    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    scripts = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import consume_office_reports as office

    lines = office._summarize_json("owner_decision_pending.json", doc)  # noqa: SLF001
    text = "\n".join(lines)

    assert "очередь дерева НЕПОЛНА" in text
    assert "own-34-kill-switch-active-13h-unnoticed" in text


def test_the_office_step_names_an_unmeasured_gap_too(tree):
    """Обратная сторона: не измерено — тоже строка, а не пустота."""
    import sys

    data, tracker = tree
    _card(tracker)
    _journal(data, [])
    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    scripts = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import consume_office_reports as office

    text = "\n".join(office._summarize_json("owner_decision_pending.json", doc))  # noqa: SLF001

    assert "полнота очереди НЕ ИЗМЕРЕНА" in text


def test_an_old_report_without_the_block_is_not_read_as_a_full_queue():
    """Отчёт, записанный ДО #270, не имеет права выглядеть измеренным."""
    import sys

    scripts = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import consume_office_reports as office

    text = "\n".join(office._summarize_json(  # noqa: SLF001
        "owner_decision_pending.json",
        {"status": "OK", "reason": "остановки нет; вопросов владельцу без ответа: 8"}))

    assert "полнота очереди НЕ ИЗМЕРЕНА" in text
    assert "отчёт старого образца" in text


# ===========================================================================
# Пропавшая карточка: три исхода вместо одного «не измерено» (цикл #273)
# ===========================================================================
# Положительный контроль здесь — ДОСЛОВНАЯ тройка из прода 17.08.2026: сторож
# держал WARNING с тремя строками `[НЕ ИЗМЕРЕНО]`, из которых две были
# доброкачественным дрейфом (`ingested` на origin), а третья — честным пробелом.
# На неисправленном модуле каждый тест ниже краснеет.

# FROZEN-DATE-OK: injected-clock — `now=` передаётся в каждом вызове, отметки
# фикстур фиксированы (см. шапку файла); календарь на вердикт не влияет.
_DRIFT_CLOSED_1 = "owner-decision-geit-i-allokator-schitayut-zhivoi-tvl-po"
_DRIFT_CLOSED_2 = "owner-decision-vozit-li-katalog-reshenii-ob-agentah-na"
_NOT_ON_ORIGIN = "owner-decision-dolgozhivuschie-agenty-krutyat-kod-mnogo"


def _commit_all_and_hide(root: Path, tracker: Path, card_ids) -> None:
    """Зафиксировать карточки на ref и убрать их файлы — состояние прод-дерева."""
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "queue")
    for card_id in card_ids:
        (tracker / f"{card_id}.md").unlink()


def test_the_real_triple_of_17_08_keeps_only_the_honest_gap(git_tree, monkeypatch):
    """Две строки объяснены дрейфом и уходят, третья ОСТАЁТСЯ не измеренной.

    Ровно то, чем сторож был занят неделю. Ложно погасить третью нельзя: её нет
    и на origin, и «не смогли найти» — это не «вопрос закрыт».
    """
    root, data, tracker = git_tree
    _card(tracker, card_id=_DRIFT_CLOSED_1, status="ingested")
    _card(tracker, card_id=_DRIFT_CLOSED_2, status="ingested")
    _commit_all_and_hide(root, tracker, [_DRIFT_CLOSED_1, _DRIFT_CLOSED_2])
    _journal(data, [_push(card_id=_DRIFT_CLOSED_1), _push(card_id=_DRIFT_CLOSED_2),
                    _push(card_id=_NOT_ON_ORIGIN)])   # третьей нет и на ref
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    missing = [u["check"] for u in doc["unchecked"] if u["check"].startswith("card_missing:")]
    assert missing == [f"card_missing:{_NOT_ON_ORIGIN}"], (
        "закрытые на origin карточки обязаны уйти из «не измерено», "
        "а отсутствующая там — остаться")
    assert {c["card_id"] for c in doc["closed_on_origin"]} == {_DRIFT_CLOSED_1, _DRIFT_CLOSED_2}
    assert all(c["origin_status"] == "ingested" for c in doc["closed_on_origin"])
    # Причина третьей строки названа СЛОВАМИ, а не сведена к «не измерено».
    assert "карточки тоже нет" in next(
        u["reason"] for u in doc["unchecked"] if u["check"].endswith(_NOT_ON_ORIGIN))
    # Дрейф — не находка: ни одна строка issues про закрытые карточки не заведена.
    assert not any(_DRIFT_CLOSED_1 in line for line in doc["issues"])


def test_a_closed_card_on_origin_stops_holding_the_warning(git_tree, monkeypatch):
    """Обратная сторона: ЕДИНСТВЕННАЯ причина WARNING объяснена ⇒ статус чистый."""
    root, data, tracker = git_tree
    _card(tracker, card_id=_DRIFT_CLOSED_1, status="ingested")
    _commit_all_and_hide(root, tracker, [_DRIFT_CLOSED_1])
    _journal(data, [_push(card_id=_DRIFT_CLOSED_1)])
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["unchecked"] == []
    assert doc["status"] == OK
    assert doc["closed_on_origin"] == [{"card_id": _DRIFT_CLOSED_1, "origin_status": "ingested"}]


def test_a_question_open_on_origin_becomes_a_finding_not_an_unchecked_line(git_tree,
                                                                          monkeypatch):
    """`needs-owner` на origin — находка СИЛЬНЕЕ прежней, а не «не измерено».

    Вопрос владельцу отправлен, он его видит, а нажатие отвечает «карточка
    исчезла»: ответить ему физически нечем.
    """
    root, data, tracker = git_tree
    _card(tracker, card_id=CARD_ID, status="needs-owner")
    _commit_all_and_hide(root, tracker, [CARD_ID])
    _journal(data, [_push(card_id=CARD_ID)])
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert not [u for u in doc["unchecked"] if u["check"].startswith("card_missing:")]
    assert doc["open_on_origin"] == [{"card_id": CARD_ID, "origin_status": "needs-owner"}]
    assert any("«карточка исчезла»" in line for line in doc["issues"])
    assert doc["status"] == WARNING
    # А во время остановки живой потерянный вопрос обязан быть CRITICAL.
    _halt(data)
    doc2 = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)
    assert doc2["status"] == CRITICAL


def test_an_unknown_status_on_origin_stays_unmeasured(git_tree, monkeypatch):
    """Не `needs-owner` ⇒ ещё не «закрыт». Список закрывающих статусов — закрытый.

    Иначе опечатка в статусе (или новый промежуточный статус) молча погасила бы
    живой вопрос — ровно тот fail-OPEN, ради которого модуль и написан.
    """
    root, data, tracker = git_tree
    _card(tracker, card_id=CARD_ID, status="in-progres")      # опечатка, не статус
    _commit_all_and_hide(root, tracker, [CARD_ID])
    _journal(data, [_push(card_id=CARD_ID)])
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    line = next(u for u in doc["unchecked"] if u["check"] == f"card_missing:{CARD_ID}")
    assert "in-progres" in line["reason"], "незнакомый статус обязан быть НАЗВАН"
    assert doc["closed_on_origin"] == [] and doc["open_on_origin"] == []
    assert doc["status"] == WARNING


def test_without_a_ref_the_line_stays_unmeasured_never_closed(tree):
    """Fail-CLOSED: «не смогли посмотреть» ≠ «вопрос закрыт».

    Дерево-песочница (CI, чистая установка) — не git-репозиторий, сверять не с
    чем. Молчаливое «закрыто» здесь и было бы ценой этой правки.
    """
    data, tracker = tree
    _journal(data, [_push()])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert doc["unchecked"][0]["check"] == f"card_missing:{CARD_ID}"
    assert "сверка с" in doc["unchecked"][0]["reason"]
    assert doc["missing_cards"]["measured"] is False
    assert doc["closed_on_origin"] == [] and doc["open_on_origin"] == []
    assert doc["status"] == WARNING


def test_one_card_resent_three_times_gives_one_line_not_three(tree):
    """Дедуп по карточке: три записи журнала об ОДНОЙ карточке — один факт.

    Карточку переотправляют (так #198 чинил кнопки `own-33`), и трижды повторённая
    строка «не измерено» об одном и том же — тот же шум, что и молчание.
    """
    data, tracker = tree
    _journal(data, [_push(pushed_at=PUSHED_AT), _push(pushed_at="2026-08-10T12:30:00+00:00"),
                    _push(pushed_at="2026-08-10T12:40:00+00:00")])

    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    assert [u["check"] for u in doc["unchecked"]] == [f"card_missing:{CARD_ID}"]


def test_the_office_step_prints_the_drift_fact_it_stopped_warning_about(git_tree,
                                                                        monkeypatch):
    """Объяснение, которого не видно, ничего не стоит.

    Строка ушла из WARNING именно потому, что мы её объяснили — и объяснение
    обязано доехать до обязательного шага 0-офис, иначе факт исчез молча.
    """
    import sys

    root, data, tracker = git_tree
    _card(tracker, card_id=_DRIFT_CLOSED_1, status="ingested")
    _commit_all_and_hide(root, tracker, [_DRIFT_CLOSED_1])
    _journal(data, [_push(card_id=_DRIFT_CLOSED_1)])
    monkeypatch.setattr("spa_core.monitoring.owner_decision_pending.ORIGIN_REF", _REF)
    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)

    scripts = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import consume_office_reports as office

    text = "\n".join(office._summarize_json("owner_decision_pending.json", doc))  # noqa: SLF001

    assert "дрейф прод↔origin" in text
    assert _DRIFT_CLOSED_1 in text and "ingested" in text
