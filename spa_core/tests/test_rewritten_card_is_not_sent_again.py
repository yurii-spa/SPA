"""Переписанную карточку нельзя отправлять заново: кнопки означают ПРЕЖНИЙ текст.

Авария 30–31.08. Карточка про открытый порт ушла владельцу; через десять минут я
измерил границу сам и ПЕРЕПИСАЛ её тело — вариант 1 сменил смысл с «загляни в
Cloudflare» на «сузить каталог». Владелец нажал 1 — по ТОМУ тексту, который получил.
Журнал отправок при этом хранил уже новые варианты, то есть перестал быть
свидетельством того, что владелец видел.

Верный приём — закрыть старую карточку и завести новую с совпадающими кнопками
(так в итоге и сделано вручную). Проверка делает его видимым: отправка отклоняется,
а отказ называет, что делать.

Отклоняется ТОЛЬКО неоднозначный случай: карточка уже уходила, ответа нет, а название
или варианты с тех пор изменились. Неизменная карточка и первая отправка не задеты —
это проверяют обратные контроли.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_HEAD = (
    "---\n"
    "trackerStatus:\n"
    "  type: owner-decision\n"
    "title: {title}\n"
    "status: needs-owner\n"
    "---\n"
    "\n"
    "## Что случилось и почему это важно\n"
    "Контекст в двух строках.\n"
    "\n"
    "## Что от тебя нужно\n"
)
_SENT = _HEAD.format(title="Вопрос про порт") + (
    "* **Вариант 1 (рекомендую) — заглянуть в панель.** Пояснение.\n"
    "* **Вариант 2 — сменить токен.** Пояснение.\n"
)
# Тот же файл, переписанный: вариант 1 теперь значит СОВСЕМ другое.
_REWRITTEN = _HEAD.format(title="Вопрос про порт") + (
    "* **Вариант 1 (рекомендую) — сузить каталог.** Пояснение.\n"
    "* **Вариант 2 — убрать агента совсем.** Пояснение.\n"
)

_CHILD = r'''
import sys, types
from pathlib import Path

sandbox, card_path = Path(sys.argv[1]), sys.argv[2]

_bot = types.ModuleType("spa_core.telegram.bot")


class _Bot:
    def send_message(self, text, **kw):
        return True


_bot.TelegramBot = _Bot
sys.modules["spa_core.telegram.bot"] = _bot

from spa_core.owner_queue.notify import notify_needs_owner

(sandbox / "returned.txt").write_text(notify_needs_owner(card_path), encoding="utf-8")
'''


def _run(sandbox: Path, card: Path) -> str:
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env["SPA_LIVE_ROOT"] = str(sandbox)
    env.pop("SPA_DATA_DIR", None)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    p = subprocess.run([sys.executable, "-c", _CHILD, str(sandbox), str(card)],
                       cwd=str(_REPO_ROOT), env=env, capture_output=True,
                       text=True, timeout=180)
    assert p.returncode == 0, f"дочерний прогон упал: {p.stderr[-1500:]}"
    return (sandbox / "returned.txt").read_text(encoding="utf-8")


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    return tmp_path


@pytest.fixture()
def card(tmp_path: Path) -> Path:
    src = tmp_path / "worktree"
    src.mkdir()
    p = src / "own-probe-rewrite.md"
    p.write_text(_SENT, encoding="utf-8")
    return p


def test_rewritten_options_are_refused(sandbox, card):
    """Ядро аварии: варианты сменили смысл после отправки."""
    first = _run(sandbox, card)
    assert "отклонена" not in first, f"первая отправка не должна отклоняться: {first}"

    card.write_text(_REWRITTEN, encoding="utf-8")
    second = _run(sandbox, card)
    assert "[переписана]" in second, (
        f"переписанная карточка ушла бы владельцу второй раз: {second}")
    assert "варианты" in second, second
    assert "новую" in second, "отказ не называет верный приём: " + second


def test_unchanged_card_is_not_refused_by_this_check(sandbox, card):
    """Обратный контроль: неизменную карточку эта проверка не трогает.

    Её может придержать анти-шторм — это ДРУГОЙ отказ, и он допустим; но пометки
    `[переписана]` быть не должно.
    """
    _run(sandbox, card)
    again = _run(sandbox, card)
    assert "[переписана]" not in again, (
        f"неизменная карточка объявлена переписанной: {again}")


def test_first_send_is_never_refused(sandbox, card):
    """Обратный контроль: карточка, которой ещё не отправляли, уходит."""
    out = _run(sandbox, card)
    assert "[переписана]" not in out, out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
