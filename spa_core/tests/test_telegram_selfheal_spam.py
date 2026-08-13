#!/usr/bin/env python3
"""Сторож не имеет права звать владельца на СВОЮ УСПЕШНУЮ работу.

Жалоба владельца 13.08 (голосом, дословно): «после того, как ты починил Telegram-бот…
потом что-то происходит, и опять у него ломается, он опять начинает тебе слать сообщение,
ты опять пишешь мне, что я всё починил, потом он опять выдаёт какую-то ошибку, и опять
начинает мне слать по кругу… не слать мне спама по 50 сообщений в день… займись
основательно, а не так, как ты её чинишь уже третий раз».

Замер по `data/alert_history.json` (13.08) — жалоба верна пофамильно:

* 14 перезапусков бота ⇒ РОВНО 26 сообщений владельцу, парами «🚨 починил сам» +
  через 5 минут «✅ снова работает». Совпадение с журналом перезапусков 1:1, без исключений.
* За 13.08 из 7 НЕПРОШЕНЫХ сообщений 6 — эта пара; седьмое — законный дневной отчёт.
  За 12.08 — 4 из 5. То есть чат владельца был занят почти целиком одной петлёй.

Две причины, обе одного класса «сторож честно отвечает на свой вопрос, а не на нужный»:

1. **Причина петли.** `_check_stale_code` объявляет CRITICAL, когда живой процесс старше
   последней правки модулей бота. Это верное измерение — и одновременно ПЛАНОВОЕ следствие
   нашей же доставки: синк кода с origin идёт перед каждым циклом. Сторож чинил это сам,
   полностью и успешно — и каждый раз звал владельца посмотреть. Прошлые починки правили
   ТОН сообщения (`alert_text`: «🔧 было сломано, починил сам» вместо «🚨 сломан») и дедуп,
   но ни одна не спросила, должно ли это доезжать до владельца вообще. Отсюда «третий раз
   чиню, а стоим на том же месте».

2. **Почему дедуп не спасал.** Повтор сравнивался по первым 80 символам ГОТОВОГО текста, а
   `push_policy._format_message` дописывает в хвост `<i>{now}</i>` с микросекундами. У
   короткой тревоги штамп попадает ВНУТРЬ этих 80 символов ⇒ два побуквенно одинаковых
   сообщения давали разные ключи и не могли совпасть в принципе. Окно в полчаса существовало
   и не ловило ничего.

Каждый тест ниже — положительный контроль: на непочиненном модуле он краснеет.
Проверка НЕ ослаблена — обнаружение, перезапуск, отчёт и код возврата прежние; гасится
только ЗВОНОК владельцу, и только когда всё сошлось (см. `is_routine_selfheal`).
Сети здесь нет.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from spa_core.alerts import telegram_client as tc
from spa_core.monitoring import telegram_health as th
from spa_core.tests._freshness import now_utc

NOW = now_utc()


# ── строители отчётов (ровно те состояния, что были в проде 13.08) ───────────


def _stale_code_finding() -> th.Finding:
    """Ровно то, что сторож писал в 04:06 / 11:46 / 13:26 13.08."""
    return th.Finding(
        "свежесть кода", th.CRITICAL,
        "процесс стартовал на 7.7ч РАНЬШЕ последней правки кода бота — "
        "исполняется старое (доставлено, но не работает)",
        restart_helps=True, routine=True,
    )


def _healed_report(*extra: th.Finding) -> th.Report:
    rep = th.Report(checked_at=NOW.isoformat())
    rep.add(th.Finding("launchd", th.OK, "задание работает, pid 88709"))
    rep.add(th.Finding("поллеры", th.OK, "ровно один, pid 88722"))
    rep.add(th.Finding("маячок", th.OK, "свежий (20с), умеет обрабатывать нажатия"))
    rep.add(_stale_code_finding())
    for f in extra:
        rep.add(f)
    rep.actions.append("перезапущен com.spa.telegram_bot (причина: свежесть кода)")
    rep.actions.append(th.HEALED_MARK + ": маячок вернулся")
    return rep


class _Spy:
    """Ловит, что именно сторож попытался сказать владельцу."""

    def __init__(self):
        self.pushed: list = []
        self.digested: list = []
        self.resolved: list = []

    def install(self, monkeypatch):
        from spa_core.telegram import push_policy

        def push_critical(event_key, severity, title, body="", **kw):
            self.pushed.append((event_key, title))
            return True

        def enqueue_digest(event_key, title, body="", **kw):
            self.digested.append((event_key, title))

        def resolve(event_key, title, body="", **kw):
            self.resolved.append((event_key, title))
            return True

        monkeypatch.setattr(push_policy, "push_critical", push_critical)
        monkeypatch.setattr(push_policy, "enqueue_digest", enqueue_digest)
        monkeypatch.setattr(push_policy, "resolve", resolve)
        return self


@pytest.fixture
def spy(monkeypatch):
    return _Spy().install(monkeypatch)


# ── 1. Сама петля ────────────────────────────────────────────────────────────


def test_routine_selfheal_does_not_call_the_owner(spy):
    """ГЛАВНЫЙ положительный контроль: авария 13.08 в чистом виде.

    Единственная непройденная проверка — «свежесть кода», починка подтверждена.
    Владельцу тут делать нечего. На непочиненном модуле здесь уходил `push_critical`
    «🔧 было сломано, починил сам» — и так 14 раз за шесть дней.
    """
    th.notify(_healed_report())

    assert spy.pushed == [], f"владельца позвали на штатную отработку: {spy.pushed}"
    assert spy.digested, "факт обязан остаться видимым — в дайджесте"
    assert spy.digested[0][0] == "telegram_down"


def test_the_paired_confirmation_dies_with_the_alarm(tmp_path, monkeypatch):
    """Вторая половина петли: «✅ снова работает» через 5 минут.

    Проверяется НЕ заглушкой, а настоящим `push_policy` на своём каталоге состояния:
    раз входа в тревогу не было, выход обязан промолчать сам. Иначе владелец получал бы
    осиротевшую галочку о починке того, о чём ему не сообщали.
    """
    from spa_core.telegram import push_policy

    sent: list = []
    monkeypatch.setattr(push_policy, "_send", lambda text: sent.append(text) or True)
    monkeypatch.setattr(push_policy, "_tg_dir", lambda *a, **k: tmp_path)

    # Такт 1: доставили код, сторож починил сам.
    th.notify(_healed_report())
    # Такт 2 (через 5 минут): всё в порядке — сторож зовёт resolve, как и раньше.
    th.notify(th.Report(status=th.OK, checked_at=NOW.isoformat()))

    assert sent == [], f"владельцу уехала пара сообщений: {sent}"
    assert push_policy.current_state("telegram_down", data_dir=tmp_path) != "bad"


def test_stale_code_is_still_detected_and_still_healed():
    """Сторож НЕ ослаблен: находка та же, красная, и по-прежнему лечится перезапуском.

    Инвариант #16 — гасится маршрут сообщения, а не проверка. Если однажды кто-то
    решит «убрать шум», сняв саму находку, этот тест покраснеет.
    """
    f = _stale_code_finding()
    assert f.status == th.CRITICAL
    assert f.restart_helps is True
    assert f.routine is True
    assert _healed_report().status == th.CRITICAL, "отчёт обязан остаться КРАСНЫМ"


def test_the_real_check_marks_stale_code_as_routine(monkeypatch, tmp_path):
    """`_check_stale_code` обязан САМ ставить `routine` — не только фикстура теста.

    Положительный контроль на разъезд: снимут метку в проде — тест покраснеет,
    хотя фикстуры выше останутся зелёными.
    """
    monkeypatch.setattr(th, "process_age_s", lambda pid: 8 * 3600.0)
    monkeypatch.setattr(th, "newest_watched_mtime", lambda root: NOW.timestamp())

    f = th._check_stale_code([42], NOW, tmp_path)

    assert f.status == th.CRITICAL and f.check == "свежесть кода"
    assert f.routine is True, "плановую причину не пометили — владельца снова позовут"


# ── 2. Молчание НЕ должно стать глухотой ─────────────────────────────────────


def test_a_real_breakage_still_calls_the_owner(spy):
    """Рядом с плановой причиной — настоящая поломка. Сообщение уходит целиком."""
    dead_beacon = th.Finding("маячок", th.CRITICAL,
                             "маячка нет — бот не объявляет, что умеет обрабатывать нажатия",
                             restart_helps=True)
    th.notify(_healed_report(dead_beacon))

    assert spy.pushed, "настоящую поломку проглотили — это хуже спама"
    assert spy.digested == []


def test_unmeasured_is_not_routine(spy):
    """fail-CLOSED: «не смогли измерить» — это отсутствие ответа, а не штатность."""
    unknown = th.Finding("поллеры", th.UNKNOWN, "не смогли перечислить процессы")
    th.notify(_healed_report(unknown))

    assert spy.pushed, "UNKNOWN ушёл в тишину — так теряют настоящие аварии"


def test_unconfirmed_heal_always_calls_the_owner(spy):
    """Перезапустили, а маячок не вернулся — бот лежит. Это к владельцу, немедленно."""
    rep = th.Report(checked_at=NOW.isoformat())
    rep.add(_stale_code_finding())
    rep.actions.append("перезапущен com.spa.telegram_bot (причина: свежесть кода)")
    rep.actions.append("ПОЧИНКА НЕ ПОДТВЕРЖДЕНА: маячок не вернулся за 90с — "
                       "бот не поднялся, нужен человек")

    th.notify(rep)

    assert spy.pushed, "непроведённую починку выдали за штатную отработку"


def test_a_healthy_report_is_not_routine_selfheal():
    """Пустой список находок не имеет права читаться как «штатно отработали»."""
    assert th.is_routine_selfheal(th.Report(status=th.OK)) is False


# ── 3. Почему дедуп не срабатывал ────────────────────────────────────────────


def _resolve_text(iso: str) -> str:
    """Текст «✅ снова работает» ровно в том виде, в каком он уходил владельцу."""
    return f"✅ <b>Телеграм-бот снова работает</b>\n\n<i>{iso}</i>"


def test_our_own_timestamp_is_not_part_of_the_dedup_key():
    """Два сообщения из прода 12.08 и 13.08 — побуквенно одно и то же событие.

    Положительный контроль: по СТАРОМУ правилу (сырые первые 80 символов) их ключи
    различались, и совпасть не могли никогда — штамп с микросекундами лежит внутри окна.
    """
    a = _resolve_text("2026-08-12T11:12:11.424298+00:00")  # FROZEN-DATE-OK: записи прода
    b = _resolve_text("2026-08-13T04:11:06.923583+00:00")  # FROZEN-DATE-OK: записи прода

    assert a[:tc._PREVIEW_LEN] != b[:tc._PREVIEW_LEN], \
        "штамп вышел за окно сравнения — тест перестал воспроизводить аварию"
    assert tc._dedup_preview(a) == tc._dedup_preview(b)


def test_the_repeat_that_reached_the_owner_is_now_suppressed(tmp_path, monkeypatch):
    """Тот самый повтор — уже был отправлен минуту назад, второй раз не уходит."""
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    earlier = _resolve_text((NOW - timedelta(seconds=90)).isoformat())
    hist = tmp_path / "alert_history.json"
    hist.write_text(json.dumps({"entries": [{
        "ts": (NOW - timedelta(seconds=90)).isoformat(),
        "preview": earlier[:tc._PREVIEW_LEN],
        "dkey": tc._dedup_preview(earlier),
        "ok": True,
    }]}), encoding="utf-8")
    monkeypatch.setattr(tc, "_HISTORY_STATE", hist)

    assert tc._duplicate_recently(_resolve_text(NOW.isoformat())) is True


def test_a_changed_fact_still_gets_through(tmp_path, monkeypatch):
    """Дедуп не стал глухотой: изменилось СОДЕРЖАНИЕ — сообщение уходит.

    Снимается ровно и только наш хвостовой штамп; любая другая разница остаётся в ключе.
    """
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    earlier = _resolve_text((NOW - timedelta(seconds=60)).isoformat())
    hist = tmp_path / "alert_history.json"
    hist.write_text(json.dumps({"entries": [{
        "ts": (NOW - timedelta(seconds=60)).isoformat(),
        "preview": earlier[:tc._PREVIEW_LEN],
        "dkey": tc._dedup_preview(earlier),
        "ok": True,
    }]}), encoding="utf-8")
    monkeypatch.setattr(tc, "_HISTORY_STATE", hist)

    other = f"🚨 <b>Телеграм-бот сломан</b>\n\n<i>{NOW.isoformat()}</i>"
    assert tc._duplicate_recently(other) is False


def test_a_message_without_our_stamp_is_untouched():
    """Сообщения без хвостового штампа сравниваются ровно как раньше."""
    plain = "🚨 <b>SPA Agent Health Alert</b>\nStatus: CRITICAL | 2 issue(s) found"
    assert tc._dedup_preview(plain) == plain[:tc._PREVIEW_LEN]


def test_a_timestamp_inside_the_body_is_kept():
    """Снимаем ТОЛЬКО хвост. Отметка времени в теле — это факт, а не оформление."""
    text = "⚠️ <b>Цикл не отработал</b>\n\nпоследний запуск <i>2026-08-01T00:00:00+00:00</i> — 3 суток"
    assert "2026-08-01" in tc._dedup_preview(text)


def test_history_keeps_the_human_preview_and_the_key_apart(tmp_path, monkeypatch):
    """Превью — для человека («кто это шлёт»), ключ — для машины. Их нельзя смешивать."""
    monkeypatch.setenv("SPA_ALERT_HISTORY_TEST", "1")
    hist = tmp_path / "alert_history.json"
    monkeypatch.setattr(tc, "_HISTORY_STATE", hist)
    text = _resolve_text(NOW.isoformat())

    tc._record_history(text, ok=True, message_id=1)

    rec = json.loads(hist.read_text())["entries"][-1]
    assert rec["preview"] == text[:tc._PREVIEW_LEN], "превью урезали — разбор потеряет смысл"
    assert rec["dkey"] == tc._dedup_preview(text)


def test_an_old_record_without_a_key_never_suppresses(tmp_path, monkeypatch):
    """Записи, сделанные ДО правки, не имеют права глушить: сомнение → шлём."""
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    earlier = _resolve_text((NOW - timedelta(seconds=60)).isoformat())
    hist = tmp_path / "alert_history.json"
    hist.write_text(json.dumps({"entries": [{
        "ts": (NOW - timedelta(seconds=60)).isoformat(),
        "preview": earlier[:tc._PREVIEW_LEN],   # старая запись: `dkey` ещё нет
        "ok": True,
    }]}), encoding="utf-8")
    monkeypatch.setattr(tc, "_HISTORY_STATE", hist)

    assert tc._duplicate_recently(_resolve_text(NOW.isoformat())) is False
