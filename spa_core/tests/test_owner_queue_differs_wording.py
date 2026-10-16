"""«Не доходят до владельца» — только про вопросы, которых в дереве нет; старая редакция — другая находка.

ARB 16.10 (карточка `inbox-arb-razobrat-trevogu-telegram-posle-pere`, п. 4/6): сторож очереди
писал «очередь этого дерева НЕПОЛНА — 5 вопрос(ов) … до владельца из этого дерева НЕ доходят
(в дереве ДРУГОЙ текст: 5): здешние счётчики про них не знают ВООБЩЕ». Замер: все пять лежат
в прод-дереве открытыми (`needs-owner`), их считают здешние счётчики и шлёт здешний бот;
копия origin — строгое надмножество (у трёх — одна строка `subject:`, у двух — дописанный
раздел). Утверждение было ложным; находка верна, но другая — «доходит в старой редакции».

Положительный контроль: на origin 8f913113 тест `differs` красный (старая строка). Обратный:
вопрос, которого в дереве нет вовсе, по-прежнему «НЕ доходят … не знают ВООБЩЕ».

Часы — ВХОД (приём №1 `.claude/rules/deployment.md`): `NOW_1330` передаётся в
`check_pending_owner_decisions(now=)`. Пометки `FROZEN-DATE-OK` здесь НЕТ намеренно: сам якорь
объявлен в `test_owner_decision_pending` и ВВОЗИТСЯ, то есть литеральной даты в этом файле нет
ни одной — освобождать нечего, а пометка утверждала бы обратное и была бы НЕПРАВДОЙ
(сторож `test_injected_clock_claim` сверяет претензию с кодом ФАЙЛА, а не с намерением автора).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from spa_core.monitoring.owner_decision_pending import check_pending_owner_decisions
from spa_core.tests.test_owner_decision_pending import (CARD_ID, NOW_1330, _card, _journal,
                                                        _push)


def _repo(tmp_path: Path):
    root = tmp_path / "repo"
    data = root / "data"
    tracker = root / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)
    data.mkdir(parents=True)

    def git(*args):
        res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
        assert res.returncode == 0, f"git {args}: {res.stderr}"

    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "test")
    _card(tracker)
    # origin несёт ДОПОЛНЕНИЕ (как пять карточек 16.10): строку метаданных
    p = tracker / f"{CARD_ID}.md"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "status: needs-owner\n", "status: needs-owner\nsubject: MONEY\n"), encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "c")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    return data, tracker


def test_open_card_with_older_text_is_said_to_reach_in_an_old_edition(tmp_path):
    data, tracker = _repo(tmp_path)
    _card(tracker)                      # дерево: тот же вопрос без строки origin
    _journal(data, [_push(buttons=True)])
    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)
    assert doc["pending_count"] == 1    # счётчики дерева его ЗНАЮТ
    lines = [i for i in doc["issues"] if CARD_ID in i]
    assert any("доходят из этого дерева в СТАРОЙ редакции" in i
               and "в дереве ДРУГОЙ текст: 1" in i
               and "дописать, не перезаписывая" in i for i in lines), doc["issues"]
    assert not any("НЕ доходят" in i or "не знают ВООБЩЕ" in i for i in lines), doc["issues"]


def test_card_absent_from_the_tree_still_does_not_reach(tmp_path):
    data, tracker = _repo(tmp_path)
    (tracker / f"{CARD_ID}.md").unlink()
    _journal(data, [])
    doc = check_pending_owner_decisions(now=NOW_1330, data_dir=data, tracker_dir=tracker)
    assert any("очередь этого дерева НЕПОЛНА" in i and "до владельца из этого дерева НЕ доходят"
               in i and "файла в дереве нет: 1" in i for i in doc["issues"]), doc["issues"]
    assert not any("СТАРОЙ редакции" in i for i in doc["issues"])
