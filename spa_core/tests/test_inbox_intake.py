"""Tests for Telegram→Inbox intake (ENV_SETUP_BRIEF_v3 · Этап 6).

The heavy offline whisper path is verified end-to-end manually (say→opus→turbo);
these unit tests cover the pure text/card logic without loading a model.

**Изоляция этого файла однажды была НЕ-ОПЕРАЦИЕЙ, и цена дошла до владельца (ADR-874,
цикл #992).** Обёртка ниже писалась как `kwargs.setdefault("tracker_dir", tmp_path)` —
то есть ПРЕДЛАГАЛА песочницу. А `save_inbox_task` передаёт `tracker_dir=tracker_dir`
ЯВНО, поэтому ключ в `kwargs` уже лежал (со значением `None`), `setdefault` не делал
НИЧЕГО, и `create_card` падал на своё умолчание — в ЖИВОЙ трекер. Замер 30.10: в
прод-трекере **18** карточек, дословно равных фикстурам этого файла («купить зонт в
пятницу» · «проверь дашборд» + расшифровка «проверь дашборд на телефоне»), с 15.10 по
30.10 — по одной на прогон набора. Из них родился вопрос владельцу
`owner-decision-utochnenie-po-zametke-prover-dashbord`, УШЁЛ в Telegram и был ОТВЕЧЕН
(`owner_answer_via: telegram`, `owner_choice: nack`, 15.10 22:05): внимание владельца
потратилось на фикстуру теста. И те же карточки ADR-860 (цикл #977) посчитал ПОВТОРОМ
ПРОСЬБЫ ВЛАДЕЛЬЦА — «все пять голосовых заданий были одной просьбой, десять суток, ни
один цикл не взял».

Поэтому обёртка теперь ЗАСТАВЛЯЕТ, а не предлагает, и рядом стоит контроль в ОБЕ
стороны (`TestTheSandboxIsForced`): он поднимает НАСТОЯЩУЮ дверь `create_card` дважды —
с заставляющей обёрткой и с прежней, предлагающей, — и требует ПРОТИВОПОЛОЖНЫХ ответов.
Без второй сцены зелёный контроль не отличил бы «изоляция работает» от «фикстура просто
не писала ничего».
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from spa_core.telegram import inbox_intake
from spa_core.owner_queue.queue import load_card


def test_title_from_text_first_nonempty_line():
    assert inbox_intake._title_from_text("\n\n купить зонт \nвторая строка") == "купить зонт"
    assert inbox_intake._title_from_text("") == "Задание из Telegram"
    long = "x" * 200
    assert inbox_intake._title_from_text(long).endswith("…")


def test_save_inbox_task_text(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox_intake, "create_card", _card_into(tmp_path))
    path, title = inbox_intake.save_inbox_task("купить зонт в пятницу", source="telegram")
    assert Path(path).parent == tmp_path, (
        f"карточка легла ВНЕ песочницы ({path}) — изоляция не сработала, и это ровно "
        f"авария ADR-874")
    assert title == "купить зонт в пятницу"
    c = load_card(path)
    assert c.tracker_type == "inbox"
    assert c.status == "new"
    assert c.fields.get("source") == "telegram"
    assert "купить зонт" in c.body
    assert "Расшифровка" not in c.body  # no transcript for a text task


def test_save_inbox_task_voice_includes_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox_intake, "create_card", _card_into(tmp_path))
    path, _title = inbox_intake.save_inbox_task(
        "проверь дашборд", source="voice", transcript="проверь дашборд на телефоне")
    assert Path(path).parent == tmp_path, (
        f"карточка легла ВНЕ песочницы ({path}) — изоляция не сработала, и это ровно "
        f"авария ADR-874")
    c = load_card(path)
    assert c.fields.get("source") == "voice"
    assert "Расшифровка голосового" in c.body
    assert "на телефоне" in c.body


def _card_into(tmp_path):
    """ЗАСТАВИТЬ ``create_card`` писать в песочницу — заставить, а не предложить.

    `kwargs["tracker_dir"] = …`, а НЕ `setdefault`: вызывающий (`save_inbox_task`)
    передаёт этот ключ ЯВНО, поэтому `setdefault` здесь был не-операцией и восемнадцать
    карточек уехали в живой трекер (ADR-874, докстринг модуля). Ключ, который зовущий
    передаёт сам, можно только ПЕРЕБИТЬ.
    """
    from spa_core.owner_queue.queue import create_card as _real

    def _wrapped(*args, **kwargs):
        kwargs["tracker_dir"] = tmp_path
        return _real(*args, **kwargs)

    return _wrapped


def _card_into_the_old_way(tmp_path):
    """Прежняя, ПРЕДЛАГАЮЩАЯ обёртка — воспроизведение аварии ADR-874 дословно.

    Живёт только ради контроля ниже: проверка, никогда не видевшая настоящей поломки, —
    украшение (`.claude/rules/deployment.md` § «Проверка сторожа сторожей»).
    """
    from spa_core.owner_queue.queue import create_card as _real

    def _wrapped(*args, **kwargs):
        kwargs.setdefault("tracker_dir", tmp_path)
        return _real(*args, **kwargs)

    return _wrapped


class TestTheSandboxIsForced:
    """Контроль изоляции в ОБЕ стороны, на НАСТОЯЩЕЙ двери `create_card`.

    «Живым» трекером в обеих сценах служит ВТОРОЙ временный каталог: вопрос «куда
    уехала карточка» надо задавать замером, а не доверием, и задавать его так, чтобы
    сам замер не трогал прод-трекер (иначе проверка аварии воспроизводила бы аварию).
    """

    @staticmethod
    def _scene(wrapper_factory):
        """→ (карточек в песочнице, карточек в «живом» трекере). Обе величины ИЗМЕРЕНЫ.

        «Живой» трекер подменяется ОДНИМ швом — `queue.TRACKER_DIR`, который
        `create_card` читает в МОМЕНТ ЗОВА. Перезагрузки модуля здесь намеренно нет:
        `importlib.reload` поменял бы объект модуля под всеми, кто уже держит ссылку,
        и цена ушла бы в соседние тесты шарда — ровно тот способ, которым этот файл
        уже один раз навредил чужому вердикту (красный `test_tracker_board_matches_cards`
        в шарде 9 прогона 41126290008).
        """
        from spa_core.owner_queue import queue as q

        with tempfile.TemporaryDirectory(prefix="adr874_live_") as live, \
                tempfile.TemporaryDirectory(prefix="adr874_sand_") as sand:
            live_p, sand_p = Path(live), Path(sand)
            was_tracker, was_create = q.TRACKER_DIR, inbox_intake.create_card
            q.TRACKER_DIR = live_p
            inbox_intake.create_card = wrapper_factory(sand_p)
            try:
                inbox_intake.save_inbox_task("купить зонт в пятницу", source="telegram")
            finally:
                q.TRACKER_DIR = was_tracker
                inbox_intake.create_card = was_create
            return (len(list(sand_p.glob("*.md"))), len(list(live_p.glob("*.md"))))

    def test_the_forcing_wrapper_keeps_the_live_tracker_untouched(self):
        in_sandbox, in_live = self._scene(_card_into)
        assert (in_sandbox, in_live) == (1, 0), (
            f"заставляющая обёртка обязана положить карточку В ПЕСОЧНИЦУ и НИЧЕГО в "
            f"живой трекер; измерено песочница={in_sandbox}, живой={in_live}")

    def test_the_offering_wrapper_is_caught_leaking_into_the_live_tracker(self):
        """ОБРАТНАЯ сцена: прежняя обёртка `setdefault` ОБЯЗАНА протечь.

        Красный здесь означал бы, что авария ADR-874 больше не воспроизводится — то
        есть что контроль выше зелен по какой-то ДРУГОЙ причине и ничего не меряет.
        """
        in_sandbox, in_live = self._scene(_card_into_the_old_way)
        assert (in_sandbox, in_live) == (0, 1), (
            f"обёртка `setdefault` обязана протечь в живой трекер (ровно авария "
            f"ADR-874): измерено песочница={in_sandbox}, живой={in_live}. Если она "
            f"больше не течёт — у `save_inbox_task` сменился способ передачи "
            f"`tracker_dir`, и контроль выше надо перечитать, а не этот снять")
