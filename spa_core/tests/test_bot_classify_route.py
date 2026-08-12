"""Живой телеграм-путь владельца при УПАВШЕМ классификаторе (авария 11.08.2026).

`_classify_route` — единственная дорога свободного текста/голоса владельца. Пока
`ask_router` отдавал падение `claude` как обычный вердикт `("unclear", …)`, эта дорога
вела в тупик: владелец получал «🤔 Не смог обработать сообщение» — то есть его как будто
НЕ ПОНЯЛИ, — а само сообщение НИГДЕ не сохранялось. Поручение, присланное в минуту, когда
классификатор лежал, исчезало молча: ни карточки, ни следа.

Теперь недоступность приходит отдельным видом `ask_router.UNAVAILABLE`, и правило простое:
не понял — значит СОХРАНИ и скажи правду. Тесты проверяют ЭФФЕКТ (родилась ли карточка,
что именно увидел владелец), а не возвращаемое значение классификатора.
"""

from __future__ import annotations

import types

import pytest

from spa_core.telegram import ask_router
from spa_core.telegram import bot as B


@pytest.fixture()
def wired(monkeypatch, tmp_path):
    """Бот без Keychain/сети + перехват отправленных сообщений и созданных карточек."""
    sent: list[str] = []
    saved: list[str] = []

    monkeypatch.setattr(B, "get_token", lambda: "T", raising=False)
    monkeypatch.setattr(B, "get_chat_id", lambda: "42", raising=False)
    bot = B.TelegramBot(token="T", chat_id="42")
    monkeypatch.setattr(bot, "send_message", lambda text, *a, **k: sent.append(text))

    from spa_core.telegram import inbox_intake as II

    def _save(text, source="telegram", transcript=None):
        saved.append(text)
        return (tmp_path / "card.md", "Заголовок задания")

    monkeypatch.setattr(II, "save_inbox_task", _save)
    return types.SimpleNamespace(bot=bot, sent=sent, saved=saved)


def _claude(stdout: str = "", rc: int = 0, boom: bool = False):
    def _run(*a, **k):
        if boom:
            raise OSError("no claude (авария 11.08)")
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr="")
    return _run


def test_outage_saves_the_message_instead_of_losing_it(wired, monkeypatch):
    """Классификатор упал ⇒ сообщение владельца СОХРАНЕНО, а не потеряно с «🤔»."""
    import subprocess
    monkeypatch.setattr(subprocess, "run", _claude(boom=True))

    wired.bot._classify_route("почини график на дашборде", "42", "telegram")

    assert wired.saved == ["почини график на дашборде"], \
        "сообщение владельца исчезло при недоступном классификаторе"
    assert len(wired.sent) == 1
    assert "недоступен" in wired.sent[0].lower(), wired.sent[0]
    assert "🤔" not in wired.sent[0], "недоступность нельзя выдавать за «я тебя не понял»"


def test_outage_reply_promises_nothing_it_cannot_do(wired, monkeypatch):
    """Ответ владельцу обязан назвать причину и судьбу сообщения, а не извиняться в пустоту."""
    import subprocess
    monkeypatch.setattr(subprocess, "run", _claude(rc=1))

    wired.bot._classify_route("что нового?", "42", "telegram")

    text = wired.sent[0]
    assert "inbox" in text.lower()          # куда легло
    assert "не потерял" in text.lower()     # что с ним будет


def test_genuine_unclear_still_asks_back_and_saves_nothing(wired, monkeypatch):
    """Обратный контроль: живой классификатор сказал UNCLEAR — переспрашиваем, карточки нет.

    Без этого починку можно было бы «сдать», начав сохранять вообще всё подряд.
    """
    import subprocess
    monkeypatch.setattr(subprocess, "run", _claude("UNCLEAR\nЭто про сайт или про агентов?"))

    wired.bot._classify_route("дашборд", "42", "telegram")

    assert wired.saved == [], "настоящее «непонятно» не должно молча плодить карточки"
    assert "🤔" in wired.sent[0]
    assert "Это про сайт или про агентов?" in wired.sent[0]


def test_task_path_unchanged(wired, monkeypatch):
    """Регресс-страховка: обычная задача идёт прежней дорогой (карточка + «понял как задачу»)."""
    import subprocess
    monkeypatch.setattr(subprocess, "run", _claude("TASK"))

    wired.bot._classify_route("построй график", "42", "telegram")

    assert wired.saved == ["построй график"]
    assert "задач" in wired.sent[0].lower()
    assert "недоступен" not in wired.sent[0].lower()


def test_question_path_unchanged(wired, monkeypatch):
    """Регресс-страховка: ответ на вопрос уезжает владельцу, карточка не рождается."""
    import subprocess
    monkeypatch.setattr(subprocess, "run", _claude("QUESTION\nСейчас 81 агент, всё зелёное."))

    wired.bot._classify_route("сколько агентов?", "42", "telegram")

    assert wired.saved == []
    assert "81 агент" in wired.sent[0]


def test_unavailable_is_not_routed_as_unclear(wired, monkeypatch):
    """Проводка: вид UNAVAILABLE обязан идти СВОЕЙ веткой, а не веткой 'unclear'."""
    import subprocess
    monkeypatch.setattr(subprocess, "run", _claude(boom=True))
    kind, _resp = ask_router.classify_and_answer("любое сообщение")
    assert kind == ask_router.UNAVAILABLE

    wired.bot._classify_route("любое сообщение", "42", "telegram")
    assert wired.saved, "ветка 'unclear' ничего не сохраняет — значит сработала не та ветка"
