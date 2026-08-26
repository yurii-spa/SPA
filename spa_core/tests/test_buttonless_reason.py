"""Почему у вопроса владельцу нет кнопок — `spa_core/telegram/buttonless_reason.py`.

КАЖДЫЙ тест — положительный контроль аварии **21.08.2026** (цикл #333):

    сторож три цикла подряд говорил «N вопросов ждут ответа БЕЗ КНОПОК» и ничего
    больше. Карточка-задание назвала ОДНУ гипотезу на оба висящих вопроса
    («починка описывала ветку, которая не доехала»). Ручной разбор дал ДВЕ разные
    причины, и ни одна с гипотезой не совпала:

      · `own-33-plist-marker-for-cycle-origin` — варианты есть, но ТОЛЬКО на
        `origin/main` (дописаны через 52 минуты после отправки); бот шлёт из
        прод-дерева, а каталог очереди туда не возит никто;
      · `own-2026-08-19-sudba-voronki-…` — записан так: «вариантов нет нигде,
        отказ разбора верен». **Опровергнуто замером #349 (22.08):** варианты
        написаны буквами «(а)/(б)» ровно по §2.4, и отказ был НАШ — форма разбору
        не была известна. Отказ остаётся (карточка задаёт два решения сразу), но
        зовётся теперь своим именем: `unreadable_options_in_card`.

Первая причина с диска не видна ВООБЩЕ — её видно только сверкой с ref. Значит
сторож, который её не спрашивает, отвечает не на тот вопрос.

Фикстуры сверки — настоящие крошечные git-репозитории (без сети): проверяется
ЭФФЕКТ на git, а не подменённая заглушка. Литеральных дат нет: время — ВХОД.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.owner_queue import origin_view
from spa_core.telegram import buttonless_reason as br

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
REF = "main"

_WITH_OPTIONS = (
    "## Что случилось и почему это важно\n\nЦикл идёт 52 раза в сутки.\n\n"
    "## Что от тебя нужно\n\n"
    "- **Вариант 1 (⭐ рекомендую) — разрешить метку.** Две строки в настройку.\n"
    "- **Вариант 2 — ничего не менять.** Источник запусков останется неизвестным.\n"
)
# До #349 здесь стояла карточка «- **(а) Похоронить.** / - **(б) Воскресить.**» под
# именем «БЕЗ вариантов»: разбор её не читал, и фикстура закрепляла ЕГО слепоту как
# свойство КАРТОЧКИ. Замер #349 опроверг это — варианты там есть и теперь разбираются,
# так что прежнее тело больше не является образцом «выбора не предлагали». Оно не
# выброшено, а переехало в `_UNREADABLE_OPTIONS` (ниже) — уже под своим настоящим
# именем и в РАСШИРЕННОМ виде, где разбор честно отказывает.
#
# Настоящий образец «выбора нет»: слово «вариант» в прозе БЕЗ перечня. Ровно эта
# строка — граница, за которую сторож `has_unparsed_options` заходить не должен:
# просьба завести несуществующий дефект такая же ложь, как «выбора не предлагали»
# под карточкой с выбором.
_WITHOUT_OPTIONS = (
    "## Что случилось и почему это важно\n\nВоронка ведёт в никуда.\n\n"
    "## Что от тебя нужно\n\n"
    "- Вариант тот же, что вчера — ничего не менять; подтверди словами.\n"
)

#: Выбор НАПИСАН, а разобрать его нельзя: ОДИН вопрос, перечень оформлен тире —
#: формы разбор не знает. Именно это состояние лечится кодом («научить `parse_options`»),
#: и ради него живёт код `unreadable_options_in_card`.
#:
#: До #359 тут стояло тело с ДВУМЯ решениями («Решение 1 …» / «Решение 2 …»), и оно
#: закрепляло за этим кодом чужое состояние: отказ там вызван не незнанием формы, а тем,
#: что вопросов больше одного, и лечится он делением карточки. Тело не выброшено — оно
#: переехало в `_TWO_DECISIONS` ниже, под свой собственный вердикт. Смысл теста («выбор
#: написан, а нам его не прочесть») не изменён ни на строку: изменился образец, который
#: этому смыслу соответствует.
_UNREADABLE_OPTIONS = (
    "## Что случилось и почему это важно\n\nВоронка ведёт в никуда.\n\n"
    "## Что от тебя нужно\n\n"
    "Варианты:\n\n"
    "— похоронить чекап (рекомендую);\n"
    "— воскресить чекап.\n"
)

#: ДВА решения в одной карточке, метки повторяются («а»/«б» в каждом). Разбор отказывает
#: по правилу «дубль ⇒ два вопроса, смешивать нельзя» (fail-CLOSED) — и это ВЕРНО.
#: Лекарство — разделить карточку, а НЕ учить разбор: выученная форма дала бы ряд кнопок,
#: первая из которых закрывает карточку со вторым вопросом внутри.
_TWO_DECISIONS = (
    "## Что случилось и почему это важно\n\nВоронка ведёт в никуда.\n\n"
    "## Что от тебя нужно\n\n"
    "**Решение 1 — судьба чекапа.** Варианты:\n"
    "- **(а) Похоронить.** Признать продукт закрытым.\n"
    "- **(б) Воскресить.** Поднять сервис заново.\n\n"
    "**Решение 2 — канал заявок.** Варианты:\n"
    "- **(а) Телеграм.** Заявки идут в чат.\n"
    "- **(б) Почта.** Заявки идут письмом.\n"
)


def _card_text(body: str, *, status: str = "needs-owner") -> str:
    return ("---\ntrackerStatus:\n  type: owner-decision\n"
            "title: \"Вопрос владельцу\"\n"
            f"status: {status}\n---\n\n{body}")


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий с каталогом очереди и веткой-«origin». Сети не касается."""
    root = tmp_path / "repo"
    (root / origin_view.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / origin_view.TRACKER_REL


def _write(root: Path, name: str, body: str, **kw) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(_card_text(body, **kw), encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


def _beacon(tmp_path: Path, *, alive: bool = True) -> Path:
    """Маячок живого обработчика нажатий. Мёртвый — просто очень старый."""
    p = tmp_path / "beacon.json"
    stamped = NOW - timedelta(seconds=0 if alive else 10_000)
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": stamped.isoformat(), "pid": 1,
        "capabilities": ["alert_actions"],
    }), encoding="utf-8")
    return p


def _explain(path, tmp_path, *, alive=True):
    return br.explain(path, now=NOW, beacon_path=_beacon(tmp_path, alive=alive), ref=REF)


# ===========================================================================
# ЯДРО АВАРИИ: варианты живут только на ref, и с диска этого не видно
# ===========================================================================
def test_options_only_on_the_ref_are_named_as_a_stale_tree_not_as_a_missing_choice(
        repo, tmp_path):
    """`own-33` 21.08: на ref варианты ЕСТЬ, в дереве — нет.

    Это ровно та причина, которую сторож не спрашивал: обе половины с диска
    выглядят одинаково («вариантов нет»), а лечатся противоположно — одна
    переносом карточки, другая переписыванием вопроса.
    """
    card = _write(repo, "own-33", _WITH_OPTIONS)
    _commit(repo)
    card.write_text(_card_text(_WITHOUT_OPTIONS), encoding="utf-8")  # дерево отстало

    reason = _explain(card, tmp_path)

    assert reason.code == br.CODE_STALE_VS_ORIGIN, reason.text
    assert reason.measured
    assert "2" in reason.text  # сколько вариантов ждёт на ref — названо числом
    assert REF in reason.text


def test_no_options_anywhere_is_an_honest_refusal_not_a_stale_tree(repo, tmp_path):
    """Выбора нет НИ ЗДЕСЬ, НИ на ref — отказ верен и лечится формой вопроса.

    Обратная сторона предыдущего теста: тот же с виду симптом обязан получить
    ДРУГОЙ код, иначе назвать причину значит переименовать её.
    """
    card = _write(repo, "own-77", _WITHOUT_OPTIONS)
    _commit(repo)

    reason = _explain(card, tmp_path)

    assert reason.code == br.CODE_NO_OPTIONS, reason.text
    assert reason.measured
    assert "ADR-075" in reason.text  # выдумывать выбор запрещено — сказано вслух


def test_a_card_absent_from_the_ref_is_not_reported_as_stale(repo, tmp_path):
    """Карточки на ref нет вовсе ⇒ «дерево отстало» было бы ложью."""
    _write(repo, "own-другая", _WITH_OPTIONS)  # ref существует, нашей карточки в нём нет
    _commit(repo)
    card = _write(repo, "own-78", _WITHOUT_OPTIONS)

    reason = _explain(card, tmp_path)

    assert reason.code == br.CODE_NO_OPTIONS
    assert "её нет вовсе" in reason.text


# ===========================================================================
# Дело НЕ в карточке: обработчик и не дошедший ремонт — разные состояния
# ===========================================================================
def test_options_parse_but_no_live_handler_is_its_own_named_cause(repo, tmp_path):
    """Варианты есть, а нажимать некому: кнопка стёрла бы сам вопрос (ADR-069)."""
    card = _write(repo, "own-79", _WITH_OPTIONS)
    _commit(repo)

    reason = _explain(card, tmp_path, alive=False)

    assert reason.code == br.CODE_HANDLER_UNAVAILABLE, reason.text
    assert reason.measured


def test_buttons_would_build_right_now_means_the_repair_simply_has_not_run(repo, tmp_path):
    """Карточка и обработчик в порядке ⇒ причина в доставке, а не в вопросе.

    Отдельный код нужен затем, чтобы не звать владельца переписывать карточку,
    с которой всё хорошо: лечится это штатным ремонтом, а не человеком.
    """
    card = _write(repo, "own-80", _WITH_OPTIONS)
    _commit(repo)

    reason = _explain(card, tmp_path, alive=True)

    assert reason.code == br.CODE_HEAL_PENDING, reason.text
    assert "heal_buttonless" in reason.remedy


# ===========================================================================
# Fail-CLOSED: «померить не смогли» не имеет права выглядеть как вердикт
# ===========================================================================
def test_when_the_ref_cannot_be_read_the_answer_is_unmeasured_not_no_options(tmp_path):
    """Каталог вне git: обе половины неразличимы — и это НАЗВАНО, а не решено.

    Молчаливый `no_options_in_card` здесь был бы вердиктом по неизмеренному:
    ровно тот класс, из-за которого владельца четыре раза спросили без кнопок.
    """
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    card = tracker / "own-81.md"
    card.write_text(_card_text(_WITHOUT_OPTIONS), encoding="utf-8")

    reason = br.explain(card, now=NOW, beacon_path=_beacon(tmp_path), ref=REF)

    assert reason.code == br.CODE_UNMEASURED, reason.text
    assert reason.measured is False
    assert "ОДИНАКОВО" in reason.text


def test_a_missing_card_file_is_not_a_missing_choice(tmp_path):
    """Файла нет ⇒ нажимать не по чему; «в карточке нет вариантов» было бы ложью."""
    reason = br.explain(tmp_path / "нет-такой.md", now=NOW, ref=REF)

    assert reason.code == br.CODE_CARD_GONE
    assert reason.measured


def test_an_unparsable_card_is_unmeasured_and_never_raises(tmp_path):
    """Сторож не имеет права уронить отчёт — даже на битой карточке."""
    card = tmp_path / "own-82.md"
    card.write_text("не карточка вовсе", encoding="utf-8")

    reason = br.explain(card, now=NOW, ref=REF)

    assert reason.code in (br.CODE_UNMEASURED, br.CODE_NO_OPTIONS)
    assert isinstance(reason.as_dict(), dict)


def test_the_verdict_is_serialisable_for_the_report(repo, tmp_path):
    """Причина обязана доехать до json отчёта целиком — код, текст и лекарство."""
    card = _write(repo, "own-83", _WITH_OPTIONS)
    _commit(repo)

    payload = _explain(card, tmp_path).as_dict()

    assert set(payload) == {"code", "text", "remedy", "measured"}
    assert json.loads(json.dumps(payload, ensure_ascii=False))["code"]


# ===========================================================================
# #349 — «выбор написан, а прочитать не смогли МЫ» ≠ «выбора не предлагали»
# ===========================================================================
def test_a_written_but_unreadable_choice_is_not_called_an_honest_refusal(repo, tmp_path):
    """Положительный контроль аварии 19.08–22.08 (три недели неотвечаемого `high`).

    `own-2026-08-19-sudba-voronki-chekapa-i-kanal-zayavok` получал от сторожа
    `no_options_in_card` с текстом «отказ верен, выдумывать выбор запрещено» и
    лекарством «переписать вопрос перечнем». Обе половины были неправдой: варианты
    в карточке написаны ровно по §2.4 — буквами, с рекомендацией, — а автор,
    послушавшись, переписал бы ВЕРНУЮ карточку.

    Разбор здесь по-прежнему отказывает, и отказ ВЕРЕН (два решения в одной
    карточке ⇒ смешивать их кнопками нельзя, fail-CLOSED). Меняется не отказ,
    а то, что о нём говорят: причина — наш разбор, а не форма вопроса.
    """
    card = _write(repo, "own-2026-08-19", _UNREADABLE_OPTIONS)
    _commit(repo)

    reason = _explain(card, tmp_path)

    assert reason.code == br.CODE_UNREADABLE_OPTIONS, reason.text
    assert reason.measured
    # Отрицательный контроль на СТАРОМ вердикте: именно он звал чинить не то.
    assert reason.code != br.CODE_NO_OPTIONS
    assert "перепис" not in reason.remedy.lower() or "не перепис" in reason.remedy.lower()


def test_two_decisions_in_one_card_are_named_as_such_not_as_our_parser_defect(repo, tmp_path):
    """Положительный контроль аварии 23.08 (цикл #359).

    Карточка `owner-decision-vnutridnevnaya-prosadka-slepota-teper-sl` (`needs-owner`
    с 18.08) задаёт ПЯТЬ независимых вопросов. Сторож называл причину отсутствия кнопок
    `unreadable_options_in_card` с лекарством «научить `parse_options` этой форме» — то
    есть звал починить отказ, который ВЕРЕН, и починка сломала бы его: выученная форма
    дала бы пять кнопок, первая из которых закрывает карточку с четырьмя открытыми
    вопросами.

    Здесь тот же класс в сжатом виде (два решения, повторяющиеся метки). Проверяем
    ровно две вещи: причина названа своим именем и лекарство ведёт к делению карточки,
    а не к разбору.
    """
    card = _write(repo, "own-two-decisions", _TWO_DECISIONS)
    _commit(repo)

    reason = _explain(card, tmp_path)

    assert reason.code == "multi_question_card", reason.text
    assert reason.measured
    # Отрицательные контроли на ОБОИХ соседних вердиктах: ни «выбора не предлагали»,
    # ни «наш дефект разбора» — оба звали чинить не то.
    assert reason.code != br.CODE_NO_OPTIONS
    assert reason.code != br.CODE_UNREADABLE_OPTIONS
    assert "раздел" in reason.remedy.lower()
    assert "parse_options" not in reason.remedy


def test_prose_without_an_enumeration_still_gets_the_honest_refusal(repo, tmp_path):
    """Обратный контроль: расширение не превратилось в «всегда наш дефект».

    Сторож, который на любую карточку отвечает «варианты есть, кнопок нет», просит
    завести НЕСУЩЕСТВУЮЩИЙ дефект — такая же ложь, как прежняя, только в другую
    сторону. Слово «вариант» в прозе перечнем не является.
    """
    card = _write(repo, "own-84", _WITHOUT_OPTIONS)
    _commit(repo)

    reason = _explain(card, tmp_path)

    assert reason.code == br.CODE_NO_OPTIONS, reason.text
    assert "ADR-075" in reason.text
