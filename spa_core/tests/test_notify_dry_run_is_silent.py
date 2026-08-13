"""Сухой прогон уведомления не имеет права оставлять след в ЖИВОМ состоянии (цикл #216).

Находка (карточка `inbox-suhoi-progon-uvedomleniya-check-pishet-v`, замерена циклом #183
и перепроверена #216 чтением `origin/main`): `orchestrator_queue.py notify … --check` —
то есть «собрать сообщение и НЕ отправлять» — **писал в живой реестр решений владельца**
`data/telegram_owner_decisions.json` и заодно копировал карточку в живой трекер. Причина —
порядок в `notify_needs_owner`: `owner_decisions.register_push(...)` стоял ДО
`if dry_run: return msg`. В живом реестре прода после этого лежала запись про карточку
`/tmp/c183_probe/…`, которой больше не существует.

Класс известен и оплачен: `data/telegram/user_prefs.json` (цикл #180), где прогон тестов
ЗАГЛУШИЛ владельцу живой чат. Проверка, меняющая то, что проверяет, — не проверка.

**Почему в дочернем процессе.** Модуль состояния сам уводит запись во временный файл под
`PYTEST_CURRENT_TEST` (правило после #180). Это спасает прод от тестов — и ровно поэтому
делает тест СЛЕПЫМ к настоящему дефекту: под pytest обе ветки пишут в одно и то же
временное место, и разницы не видно. Поэтому эффект меряется там, где боевая ветка
действительно исполняется: дочерний процесс без `PYTEST_CURRENT_TEST`, а живой корень
уведён в песочницу штатным `SPA_LIVE_ROOT` (тот же механизм, которым пользуется
пред-деплойный гейт). Так проверяется НАСТОЯЩИЙ путь `_state_path() -> STATE_PATH`,
а не его тестовый обход.

Контроль в обе стороны обязателен: «ничего не пишет» легко получить, сломав уведомление
насовсем. Поэтому рядом с «сухой прогон молчит» стоит «настоящая отправка регистрирует» —
потерять оформление можно, потерять вопрос владельцу нельзя (границы карточки).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from spa_core.telegram import owner_decisions

_REPO_ROOT = Path(__file__).resolve().parents[2]

CARD_TEXT = (
    "---\n"
    "trackerStatus:\n"
    "  type: owner-decision\n"
    "title: Вопрос про доставку\n"
    "status: needs-owner\n"
    "---\n"
    "\n"
    "## Что случилось и почему это важно\n"
    "Контекст в двух строках.\n"
    "\n"
    "## Что от тебя нужно\n"
    "* **Вариант 1 (рекомендую) — сделать так.** Пояснение.\n"
    "* **Вариант 2 — сделать иначе.** Пояснение.\n"
)

# Дочерний прогон боевой ветки: без PYTEST_CURRENT_TEST, живое состояние — в песочнице.
_CHILD = r'''
import sys, types
from pathlib import Path

sandbox, card_path, mode = Path(sys.argv[1]), sys.argv[2], sys.argv[3]

# Подменяем бот ДО первого импорта: настоящий лезет в Keychain и в живой чат.
_bot_mod = types.ModuleType("spa_core.telegram.bot")


class _Bot:
    def send_message(self, text, **kw):
        (sandbox / "sent.txt").write_text(text, encoding="utf-8")
        return True


_bot_mod.TelegramBot = _Bot
sys.modules["spa_core.telegram.bot"] = _bot_mod

from spa_core.owner_queue.notify import notify_needs_owner

msg = notify_needs_owner(card_path, dry_run=(mode == "dry"))
(sandbox / "returned.txt").write_text(msg, encoding="utf-8")
'''


def _run_child(sandbox: Path, card: Path, mode: str) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env["SPA_LIVE_ROOT"] = str(sandbox)          # живое состояние → песочница
    env.pop("SPA_DATA_DIR", None)                # иначе data/ уедет мимо песочницы
    env["PYTHONPATH"] = str(_REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD, str(sandbox), str(card), mode],
        cwd=str(_REPO_ROOT), env=env, capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"дочерний прогон упал: {proc.stderr[-2000:]}"


def _state_file(sandbox: Path) -> Path:
    return sandbox / "data" / "telegram_owner_decisions.json"


def _live_tracker(sandbox: Path) -> Path:
    return sandbox / "nimbalyst-local" / "tracker"


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    return tmp_path


@pytest.fixture()
def card(tmp_path: Path) -> Path:
    # Карточка ВНЕ песочницы — как в жизни: сессия работает из своего worktree.
    src = tmp_path / "worktree"
    src.mkdir()
    p = src / "own-probe-216.md"
    p.write_text(CARD_TEXT, encoding="utf-8")
    return p


# ── сухой прогон: ни одной записи ────────────────────────────────────────────


def test_dry_run_does_not_create_the_owner_decisions_registry(sandbox, card):
    """`--check` не имеет права ЗАВЕСТИ живой реестр решений владельца."""
    _run_child(sandbox, card, "dry")
    assert not _state_file(sandbox).exists(), (
        "сухой прогон создал живой реестр решений владельца — "
        "это и есть дефект #209/#216"
    )


def test_dry_run_does_not_append_to_an_existing_registry(sandbox, card):
    """Реестр уже есть (боевой случай) — сухой прогон обязан оставить его БАЙТ В БАЙТ."""
    before = {"schema_version": 1, "pushes": [
        {"pid": "deadbeef", "card": "x.md", "card_id": "x", "title": "старое",
         "pushed_at": "2026-08-01T00:00:00+00:00", "options": [], "buttons": False,
         "choice": None},
    ]}
    _state_file(sandbox).write_text(json.dumps(before), encoding="utf-8")
    raw_before = _state_file(sandbox).read_bytes()

    _run_child(sandbox, card, "dry")

    assert _state_file(sandbox).read_bytes() == raw_before, (
        "сухой прогон дописал запись в живой реестр"
    )


def test_dry_run_does_not_copy_the_card_into_the_live_tracker(sandbox, card):
    """Вторая живая запись того же вызова — копия карточки в трекер прода."""
    _run_child(sandbox, card, "dry")
    assert not (_live_tracker(sandbox) / card.name).exists(), (
        "сухой прогон материализовал карточку в живом трекере"
    )


def test_dry_run_still_returns_the_real_message(sandbox, card):
    """Молчание в состоянии — не молчание в тексте: сообщение обязано собраться."""
    _run_child(sandbox, card, "dry")
    msg = (sandbox / "returned.txt").read_text(encoding="utf-8")
    assert "Вопрос про доставку" in msg
    assert "own-probe-216.md" in msg
    assert not (sandbox / "sent.txt").exists(), "сухой прогон ОТПРАВИЛ сообщение"


# ── обратный контроль: настоящая отправка регистрирует ───────────────────────


def test_real_send_registers_the_push(sandbox, card):
    """Положительный контроль. Без него «ничего не пишет» достигается поломкой кнопок."""
    _run_child(sandbox, card, "real")

    doc = json.loads(_state_file(sandbox).read_text(encoding="utf-8"))
    ids = [r.get("card_id") for r in doc["pushes"]]
    assert ids == ["own-probe-216"], f"настоящая отправка не зарегистрировалась: {doc}"
    assert (sandbox / "sent.txt").exists(), "настоящая отправка не дошла до бота"


def test_real_send_still_materializes_the_card(sandbox, card):
    """Копия карточки в живом трекере — условие работоспособности кнопки (#178)."""
    _run_child(sandbox, card, "real")
    assert (_live_tracker(sandbox) / card.name).is_file(), (
        "карточка не перенесена в живой трекер — нажатие вернёт «карточка исчезла»"
    )


def test_dry_and_real_send_the_same_text(sandbox, card, tmp_path):
    """Сухой прогон обязан показывать РОВНО то, что уедет: иначе он бесполезен.

    Ради этого `prepare_push` и `register_push` собирают текст одним и тем же кодом.
    """
    _run_child(sandbox, card, "dry")
    dry_msg = (sandbox / "returned.txt").read_text(encoding="utf-8")

    other = tmp_path / "sandbox2"
    (other / "data").mkdir(parents=True)
    _run_child(other, card, "real")
    real_msg = (other / "returned.txt").read_text(encoding="utf-8")

    assert dry_msg == real_msg


# ── единица, из которой собран порядок ───────────────────────────────────────


def test_prepare_push_writes_nothing(tmp_path):
    """`prepare_push` — это `register_push` минус запись, и ничего больше."""
    card = tmp_path / "own-unit.md"
    card.write_text(CARD_TEXT, encoding="utf-8")
    state = tmp_path / "state.json"

    prep = owner_decisions.prepare_push(card, "Вопрос про доставку", CARD_TEXT)
    assert not state.exists()
    assert prep.pid == owner_decisions.make_pid(card.stem)
    assert "Вопрос про доставку" in prep.text

    registered = owner_decisions.register_push(
        card, "Вопрос про доставку", CARD_TEXT,
        state_path=state, live_root=tmp_path / "live",
    )
    assert registered.pid == prep.pid
    assert registered.text == prep.text
    doc = json.loads(state.read_text(encoding="utf-8"))
    assert [r["card_id"] for r in doc["pushes"]] == ["own-unit"]
