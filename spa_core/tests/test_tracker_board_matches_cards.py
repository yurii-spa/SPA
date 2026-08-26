"""Сторож: `nimbalyst-local/tracker/_BOARD.md` обязан СОВПАДАТЬ с frontmatter карточек.

**Замер живой аварии 2026-08-17 (это и есть положительный контроль).** `CLAUDE.md` §1 велит
читать доску ПЕРВОЙ, «не открывая 56 файлов». В тот день доска врала о трёх карточках из 508:

    inbox-issledovatel-kandidatov-schitaet-chto-ak.md   доска='new'            карточка='done'
    inbox-slichenie-imen-protokolov-podstrokoi-vyr.md   доска='<НЕТ НА ДОСКЕ>' карточка='new'
    inbox-vtoroi-issledovatelskii-agent-schitaet-o.md   доска='<НЕТ НА ДОСКЕ>' карточка='done'

Из-за этого дважды за день бралась УЖЕ ЗАКРЫТАЯ работа. Причина — не в сборщике: он из тех же
карточек собирает верную доску. Коммит `223240f14` привёз доску, снятую в МОМЕНТ создания
карточки (`new`), а последующие мутации карточек доску не пересобрали, и в git уехал снимок
на два события старше собственного коммита. Правило «регенерь после мутации» существовало и
не сработало — поэтому здесь сторож, а не ещё одна строка правила.

**Что этот файл проверяет — и чего НЕ проверяет.** Он сверяет ОТОБРАЖЕНИЕ со статусами
карточек; статусы карточек он не трогает и трогать не имеет права (инвариант 14). Красный
сторож чинится пересборкой доски (`python3 scripts/build_tracker_board.py`), НИКОГДА —
правкой статуса карточки под доску.

Литеральных дат здесь нет: время у доски — вход (`render_board(cards, now=...)`), календарь на
тесты не влияет (`.claude/rules/deployment.md`, «время в тестах»).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKER_DIR = REPO_ROOT / "nimbalyst-local" / "tracker"
BUILDER = REPO_ROOT / "scripts" / "build_tracker_board.py"


def _load_builder():
    """Сборщик грузится ИЗ СВОЕГО дерева по абсолютному пути (он же — предмет проверки)."""
    spec = importlib.util.spec_from_file_location("_board_under_test", BUILDER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _card(name: str, status: str, title: str, tracker: Path) -> Path:
    p = tracker / name
    p.write_text(
        f"---\ntrackerStatus:\n  type: inbox\ntitle: \"{title}\"\nstatus: {status}\n---\n\nтело\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture()
def sandbox(tmp_path: Path):
    """Песочница-трекер: настоящий трекер репозитория тесты НЕ переписывают."""
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    return tracker


# --------------------------------------------------------------------------------------
# Положительные контроли — воспроизведение аварии 17.08. Каждый обязан краснеть на дефекте.
# --------------------------------------------------------------------------------------

def test_stale_status_on_board_is_caught(sandbox: Path) -> None:
    """АВАРИЯ №1: карточка закрыта (`done`), доска всё ещё показывает `new`."""
    board = _load_builder()
    _card("inbox-a.md", "new", "карточка А", sandbox)
    board.atomic_write(sandbox / "_BOARD.md",
                       board.render_board(board.collect_cards(sandbox)))
    # карточку закрыли БЕЗ пересборки доски — ровно то, что уехало в 223240f14
    _card("inbox-a.md", "done", "карточка А", sandbox)

    drift = board.board_drift(sandbox)
    assert drift == [("inbox-a.md", "new", "done")], drift


def test_card_missing_from_board_is_caught(sandbox: Path) -> None:
    """АВАРИЯ №2: карточка есть на диске, но доски о ней не знает вовсе."""
    board = _load_builder()
    board.atomic_write(sandbox / "_BOARD.md",
                       board.render_board(board.collect_cards(sandbox)))
    _card("inbox-b.md", "new", "карточка Б", sandbox)

    drift = board.board_drift(sandbox)
    assert drift == [("inbox-b.md", "<НЕТ НА ДОСКЕ>", "new")], drift


def test_card_deleted_but_still_on_board_is_caught(sandbox: Path) -> None:
    """Обратная сторона: доска показывает карточку, которой на диске уже нет."""
    board = _load_builder()
    p = _card("inbox-c.md", "new", "карточка В", sandbox)
    board.atomic_write(sandbox / "_BOARD.md",
                       board.render_board(board.collect_cards(sandbox)))
    p.unlink()

    drift = board.board_drift(sandbox)
    assert drift == [("inbox-c.md", "new", "<НЕТ КАРТОЧКИ>")], drift


def test_missing_board_is_drift_not_silence(sandbox: Path) -> None:
    """Fail-CLOSED: доски нет ⇒ расхождение по каждой карточке, а не «нечего сверять»."""
    board = _load_builder()
    _card("inbox-d.md", "new", "карточка Г", sandbox)
    assert board.board_drift(sandbox) == [("inbox-d.md", "<НЕТ НА ДОСКЕ>", "new")]


def test_freshly_built_board_has_no_drift(sandbox: Path) -> None:
    """Отрицательный контроль: сверка не краснеет на верном состоянии (иначе её отключат)."""
    board = _load_builder()
    _card("inbox-e.md", "new", "карточка Д", sandbox)
    _card("inbox-f.md", "done", "карточка Е", sandbox)
    _card("own-g.md", "needs-owner", "вопрос владельцу", sandbox)
    board.atomic_write(sandbox / "_BOARD.md",
                       board.render_board(board.collect_cards(sandbox)))
    assert board.board_drift(sandbox) == []


def test_cli_check_refuses_with_code_1_and_names_the_cards(sandbox: Path) -> None:
    """`--check` — та же сверка снаружи: код 1 и ИМЕНА расходящихся карточек в stderr."""
    board = _load_builder()
    _card("inbox-h.md", "new", "карточка Ж", sandbox)
    board.atomic_write(sandbox / "_BOARD.md",
                       board.render_board(board.collect_cards(sandbox)))
    _card("inbox-h.md", "done", "карточка Ж", sandbox)

    res = subprocess.run(
        [sys.executable, str(BUILDER), "--tracker-dir", str(sandbox), "--check"],
        capture_output=True, text=True,
    )
    assert res.returncode == 1, res.stdout + res.stderr
    assert "inbox-h.md" in res.stderr
    assert "done" in res.stderr

    # и наоборот: после пересборки — код 0
    subprocess.run([sys.executable, str(BUILDER), "--tracker-dir", str(sandbox)],
                   capture_output=True, text=True, check=True)
    ok = subprocess.run(
        [sys.executable, str(BUILDER), "--tracker-dir", str(sandbox), "--check"],
        capture_output=True, text=True,
    )
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_check_does_not_rewrite_the_board(sandbox: Path) -> None:
    """Сверка ЧИТАЕТ. Если бы она чинила молча, храповик перестал бы что-либо держать."""
    board = _load_builder()
    _card("inbox-i.md", "new", "карточка З", sandbox)
    board.atomic_write(sandbox / "_BOARD.md",
                       board.render_board(board.collect_cards(sandbox)))
    _card("inbox-i.md", "done", "карточка З", sandbox)
    before = (sandbox / "_BOARD.md").read_text(encoding="utf-8")

    subprocess.run([sys.executable, str(BUILDER), "--tracker-dir", str(sandbox), "--check"],
                   capture_output=True, text=True)
    assert (sandbox / "_BOARD.md").read_text(encoding="utf-8") == before


# --------------------------------------------------------------------------------------
# Причина №2: `set-status` пересобирал доску СВОЕГО дерева, а карточку менял в указанном
# --------------------------------------------------------------------------------------

def test_set_status_rebuilds_the_board_of_the_cards_own_tracker(sandbox: Path) -> None:
    """`set-status` принимает ПУТЬ — он может указывать в соседнее дерево (worktree §3.4).

    До починки CLI менял статус там, куда показывает путь, а доску пересобирал в своём
    дереве: карточка становилась `done`, а её доска продолжала звать её `new`.
    """
    board = _load_builder()
    _card("inbox-k.md", "new", "карточка К", sandbox)
    board.atomic_write(sandbox / "_BOARD.md",
                       board.render_board(board.collect_cards(sandbox)))
    assert board.board_status_map((sandbox / "_BOARD.md").read_text(encoding="utf-8")) \
        == {"inbox-k.md": "new"}

    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "orchestrator_queue.py"),
         "set-status", str(sandbox / "inbox-k.md"), "done"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert board.board_drift(sandbox) == [], (
        "доска чужого трекера не пересобрана: " + str(board.board_drift(sandbox)))


# --------------------------------------------------------------------------------------
# Доска называет свою дату (иначе читатель не отличит свежий индекс от вчерашнего)
# --------------------------------------------------------------------------------------

def test_board_states_its_own_build_time(sandbox: Path) -> None:
    """Время — ВХОД: тест передаёт фиксированный `now`, календарь на него не влияет."""
    board = _load_builder()
    _card("inbox-j.md", "new", "карточка И", sandbox)
    now = datetime(2026, 8, 17, 14, 5, 9, tzinfo=timezone.utc)
    text = board.render_board(board.collect_cards(sandbox), now=now)
    assert f"{board.BUILT_AT_PREFIX}2026-08-17T14:05:09Z" in text


def test_live_board_states_a_build_time() -> None:
    """Живая доска обязана нести отметку сборки — читателю нужен её возраст."""
    if not (TRACKER_DIR / "_BOARD.md").exists():
        pytest.skip("трекера нет в этом дереве")
    board = _load_builder()
    text = (TRACKER_DIR / "_BOARD.md").read_text(encoding="utf-8")
    assert board.BUILT_AT_PREFIX in text, "доска не называет собственную дату сборки"


# --------------------------------------------------------------------------------------
# Храповик на живом трекере — тот самый красный, ради которого всё писалось
# --------------------------------------------------------------------------------------

def test_live_board_matches_live_cards() -> None:
    """Доска этого дерева обязана совпадать с его карточками.

    Красный чинится пересборкой доски (`python3 scripts/build_tracker_board.py`), а НЕ
    правкой статусов карточек под доску (инвариант 14) и не отключением сторожа
    (инвариант 16).
    """
    if not TRACKER_DIR.exists():
        pytest.skip("трекера нет в этом дереве")
    board = _load_builder()
    drift = board.board_drift(TRACKER_DIR)
    assert drift == [], (
        f"_BOARD.md расходится с карточками ({len(drift)}): "
        + "; ".join(f"{n}: доска={s!r} карточка={r!r}" for n, s, r in drift)
        + " — пересобрать: python3 scripts/build_tracker_board.py"
    )
