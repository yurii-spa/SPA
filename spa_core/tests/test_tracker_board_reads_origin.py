"""Сторож: `_BOARD.md` обязан читать статус ТАМ ЖЕ, где его читает `orchestrator_queue.py`.

**Замер живой аварии 2026-08-30 (#436) — это и есть положительный контроль.** Один и тот же
вход, прод-дерево `nimbalyst-local/tracker`, один и тот же момент:

    python3 scripts/orchestrator_queue.py list --status needs-owner   →   1
    _BOARD.md, строка «ждёт владельца»                                 →  25

Из 25 двадцать три на `origin/main` уже `ingested`: владелец ответил 25.08 одной сводкой
«все одобряю», и в origin-копиях этих карточек стоит секция «✅ Ответ владельца» и поле
`resolved:`. Ещё 307 карточек живут на `origin`, а файла в прод-дереве нет — доска не
показывала их вовсе. То есть доска врала в ОБЕ стороны сразу, как очередь до #147.

**Почему прежний сторож молчал.** `test_tracker_board_matches_cards` сверяет доску с
карточками ТОГО ЖЕ дерева. Обе стороны устаревают вместе, поэтому он зелён по построению —
он сверяет две КОПИИ, а не копию с источником. Правило «дочитать карточку с origin» доехало
до одного читателя (CLI, #147) и не доехало до второго — до файла, который `CLAUDE.md` §1
велит читать ПЕРВЫМ каждой сессии.

Литеральных дат здесь нет: время у доски — вход (`render_board(cards, now=...)`).
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER = REPO_ROOT / "scripts" / "build_tracker_board.py"


def _load_builder():
    """Сборщик грузится ИЗ СВОЕГО дерева по абсолютному пути (он же — предмет проверки)."""
    spec = importlib.util.spec_from_file_location("_board_origin_under_test", BUILDER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert out.returncode == 0, f"git {args}: {out.stderr}"
    return out.stdout


def _card_text(status: str, title: str, extra: str = "") -> str:
    return (f"---\ntrackerStatus:\n  type: owner-decision\ntitle: \"{title}\"\n"
            f"status: {status}\n{extra}---\n\nтело карточки\n")


@pytest.fixture()
def repo(tmp_path: Path):
    """Настоящий git-репозиторий с веткой-ref: сверка меряет git, подделать её нечем.

    Ref называется `origin/main` не через `remote` (сети в тестах нет), а веткой с таким
    именем — `git show origin/main:path` читает её одинаково.
    """
    root = tmp_path / "repo"
    tracker = root / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)
    _git(tmp_path, "init", "-q", str(root))
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    return root, tracker


def _commit_as_origin(root: Path, msg: str = "origin") -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)
    _git(root, "branch", "-f", "origin/main", "HEAD")


def _tree_left_behind(root: Path, card: Path, was: str, now: str) -> None:
    """Воспроизвести ровно ту последовательность, что даёт `stale` в жизни.

    `stale` — не «локальная копия отличается», а «содержимое локальной копии найдено в
    ИСТОРИИ origin для её же пути»: карточка была запушена в состоянии `was`, потом цикл
    в worktree перевёл её в `now` и запушил, а прод-дерево осталось на первой версии
    (бот пишет туда, инжест идёт не там). Фикстура, коммитящая только конечное состояние,
    даёт `diverged` — и проверяла бы не тот класс.
    """
    card.write_text(was, encoding="utf-8")
    _commit_as_origin(root, "версия, на которой осталось дерево")
    card.write_text(now, encoding="utf-8")
    _commit_as_origin(root, "версия, уехавшая на origin")
    card.write_text(was, encoding="utf-8")   # дерево так и не обновилось


# --------------------------------------------------------------------------------------
# Положительные контроли — воспроизведение аварии 30.08. Каждый обязан краснеть на дефекте.
# --------------------------------------------------------------------------------------

def test_answered_question_is_not_shown_as_waiting(repo) -> None:
    """АВАРИЯ: владелец ОТВЕТИЛ (на origin `ingested`), доска показывает `needs-owner`.

    Ровно 23 из 25 строк «ждёт владельца» 30.08. Это не косметика: `CLAUDE.md` §1 велит
    читать доску первой, и каждая сессия начинала с числа, завышенного в 12 раз.
    """
    root, tracker = repo
    card = tracker / "own-otvechennyi.md"
    title = "вопрос, на который владелец ответил"
    _tree_left_behind(root, card, _card_text("needs-owner", title),
                      _card_text("ingested", title))

    board = _load_builder()
    cards = board.collect_cards(tracker)
    assert [c["status"] for c in cards] == ["needs-owner"], "предпосылка: на диске старая копия"

    resolved, verdict = board.resolve_against_origin(cards, tracker, ref="origin/main")
    assert verdict["state"] == board.ORIGIN_MEASURED, verdict
    assert [c["status"] for c in resolved] == ["ingested"], resolved
    assert verdict["stale_status_changed"] == 1, verdict
    assert resolved[0]["status_from"] == "origin"

    text = board.render_board(resolved, origin=verdict)
    assert "ждёт владельца: **0**" in text, text[:600]


def test_genuinely_open_question_survives(repo) -> None:
    """ОБРАТНЫЙ контроль: настоящий открытый вопрос обязан остаться на доске.

    Без него «починка» свелась бы к «не показывать ничего» и была бы зелёной.
    """
    root, tracker = repo
    (tracker / "own-zhivoi.md").write_text(_card_text("needs-owner", "живой вопрос"),
                                           encoding="utf-8")
    _tree_left_behind(root, tracker / "own-otvechennyi.md",
                      _card_text("needs-owner", "отвеченный"),
                      _card_text("ingested", "отвеченный"))

    board = _load_builder()
    resolved, verdict = board.resolve_against_origin(
        board.collect_cards(tracker), tracker, ref="origin/main")
    by = {c["file"]: c["status"] for c in resolved}
    assert by == {"own-otvechennyi.md": "ingested", "own-zhivoi.md": "needs-owner"}, by
    text = board.render_board(resolved, origin=verdict)
    assert "ждёт владельца: **1**" in text
    assert "живой вопрос" in text


def test_local_edit_is_not_overwritten(repo) -> None:
    """ОБРАТНЫЙ контроль: карточка со СВОЕЙ правкой (`diverged`) не переписывается.

    Кто из двух новее — не измерено, и молча выбрать сторону нельзя. Та же граница, что
    у CLI, и по той же причине: read-through лечит доказанное отставание, а не разногласие.
    """
    root, tracker = repo
    card = tracker / "own-svoya-pravka.md"
    card.write_text(_card_text("needs-owner", "исходная"), encoding="utf-8")
    _commit_as_origin(root)
    # правка, которой на origin не было НИКОГДА ⇒ это не «прежняя версия», а расхождение
    card.write_text(_card_text("needs-owner", "исходная", extra="priority: high\n"),
                    encoding="utf-8")

    board = _load_builder()
    resolved, verdict = board.resolve_against_origin(
        board.collect_cards(tracker), tracker, ref="origin/main")
    assert resolved[0]["status_from"] == "tree", resolved
    assert verdict["diverged"] == 1, verdict
    assert verdict["stale_status_changed"] == 0, verdict


def test_claim_is_never_lost_to_read_through(repo) -> None:
    """АВАРИЯ, которую починка могла ВНЕСТИ: захват карточки — состояние ЭТОГО дерева.

    Сторож расхождения объявляет ключи захвата не содержимым (`strip_claim_keys`), поэтому
    файл, отличающийся от origin ТОЛЬКО свежим захватом, признаётся «доказанно прежним».
    Переписав его целиком, доска показала бы занятую карточку свободной — и её взяла бы
    вторая сессия (столкновение 30.07, ради которого захват и заведён).
    """
    root, tracker = repo
    _tree_left_behind(
        root, tracker / "inbox-zanyataya.md",
        _card_text("new", "карточка в работе",
                   extra="claimed_by: cycle-60034\nclaimed_at: 2026-08-30T22:00:00Z\n"),
        _card_text("new", "карточка в работе"))

    board = _load_builder()
    resolved, _ = board.resolve_against_origin(
        board.collect_cards(tracker), tracker, ref="origin/main")
    assert resolved[0]["claimed_by"] == "cycle-60034", resolved


def test_claim_on_ref_is_picked_up_when_tree_has_none(repo) -> None:
    """Вторая сторона того же правила: захват, которого в дереве нет, берётся с ref.

    Обе стороны — в сторону «занято»: это осторожный ответ, а не симметрия ради симметрии.
    """
    root, tracker = repo
    _tree_left_behind(root, tracker / "inbox-zanyataya-na-origin.md",
                      _card_text("new", "карточка"),
                      _card_text("new", "карточка", extra="claimed_by: cycle-777\n"))

    board = _load_builder()
    resolved, _ = board.resolve_against_origin(
        board.collect_cards(tracker), tracker, ref="origin/main")
    assert resolved[0]["claimed_by"] == "cycle-777", resolved


def test_closed_card_holds_nobody(repo) -> None:
    """Терминальность считается по РАЗРЕШЁННОМУ статусу: закрытую карточку никто не держит.

    Иначе доска показала бы `claimed_by` у карточки, которая на origin уже `done`.
    """
    root, tracker = repo
    card = tracker / "inbox-zakrytaya.md"
    _tree_left_behind(root, card,
                      _card_text("new", "закрытая", extra="claimed_by: cycle-60034\n"),
                      _card_text("done", "закрытая"))

    board = _load_builder()
    resolved, _ = board.resolve_against_origin(
        board.collect_cards(tracker), tracker, ref="origin/main")
    assert resolved[0]["status"] == "done"
    assert resolved[0]["claimed_by"] == "", resolved


# --------------------------------------------------------------------------------------
# Третий исход: «сверить не удалось» обязан звучать иначе, чем «сверено и совпало».
# --------------------------------------------------------------------------------------

def test_unmeasured_is_said_out_loud(tmp_path: Path) -> None:
    """Каталог вне репозитория ⇒ сверки нет. Доска собирается, но ГОВОРИТ, чего не знает.

    Молчание здесь неотличимо от «сверено и совпало» — именно за эту неотличимость
    проект платит чаще всего. Fail-CLOSED к утверждению, а не к сборке: потерять доску
    целиком хуже, чем собрать её с честной пометкой.
    """
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    (tracker / "own-a.md").write_text(_card_text("needs-owner", "вопрос"), encoding="utf-8")

    board = _load_builder()
    cards = board.collect_cards(tracker)
    resolved, verdict = board.resolve_against_origin(cards, tracker, ref="origin/main")
    assert verdict["state"] == board.ORIGIN_UNMEASURED, verdict
    assert verdict["reason"], "причина обязана быть названа"
    assert [c["status"] for c in resolved] == ["needs-owner"], "статусы остаются местными"

    text = board.render_board(resolved, origin=verdict)
    assert "НЕ ИЗМЕРЕНА" in text, text[:600]
    assert verdict["reason"] in text


def test_measured_and_unmeasured_headers_differ(repo) -> None:
    """Положительный контроль на САМУ строку вердикта: два исхода не должны совпадать.

    Строка шапки — единственное, что читатель доски видит о сверке; будь она одинаковой,
    «не измерено» стало бы неотличимо от «измерено» ровно там, где это решает.
    """
    root, tracker = repo
    (tracker / "own-a.md").write_text(_card_text("needs-owner", "вопрос"), encoding="utf-8")
    _commit_as_origin(root)

    board = _load_builder()
    measured = board.origin_note({"state": board.ORIGIN_MEASURED, "ref": "origin/main",
                                  "ref_sha": "0123456789", "stale_status_changed": 3,
                                  "hidden": 7, "diverged": 0, "unread": 0})
    unmeasured = board.origin_note({"state": board.ORIGIN_UNMEASURED, "reason": "нет репозитория"})
    assert measured != unmeasured
    assert "НЕ ИЗМЕРЕНА" in unmeasured and "НЕ ИЗМЕРЕНА" not in measured
    assert "**3**" in measured and "**7**" in measured
    assert board.origin_note(None) != measured
    assert "НЕ ИЗМЕРЕНА" in board.origin_note(None)


def test_check_mode_uses_the_same_resolution_as_the_build(repo) -> None:
    """Сборка и её сторож (`--check`) обязаны судить об одном статусе одинаково.

    Разойдись они — `--check` требовал бы пересобрать доску в неверную сторону, и правило
    «красный сторож чинится пересборкой» приводило бы к вранью. Это положительный контроль
    на ПРОВОДКУ: без вызова резолвера в `board_drift` тест краснеет, хотя сборка верна.
    """
    root, tracker = repo
    _tree_left_behind(root, tracker / "own-otvechennyi.md",
                      _card_text("needs-owner", "отвеченный"),
                      _card_text("ingested", "отвеченный"))

    board = _load_builder()
    cards, verdict = board.resolve_against_origin(board.collect_cards(tracker), tracker,
                                                  ref="origin/main")
    board.atomic_write(tracker / "_BOARD.md", board.render_board(cards, origin=verdict))

    assert board.board_drift(tracker, ref="origin/main",
                             origin_check=True) == [], "доска собрана этим же правилом"
    # А доска, собранная БЕЗ сверки, при сверке ТЕМ ЖЕ правилом обязана быть названа
    # расходящейся: это и есть проводка — без вызова резолвера в `board_drift` пусто.
    board.atomic_write(tracker / "_BOARD.md",
                       board.render_board(board.collect_cards(tracker)))
    assert board.board_drift(tracker, ref="origin/main", origin_check=True) == [
        ("own-otvechennyi.md", "needs-owner", "ingested")]


def test_drift_mode_is_taken_from_the_board_itself(repo) -> None:
    """Сверять надо в том режиме, в каком доска СОБРАНА, — и спрашивает об этом саму доску.

    Иначе сторож требует пересборки в сторону, которой никто не производит: доску после
    каждой мутации карточки пересобирает `_rebuild_board` БЕЗ сверки (она стоит ~84 с),
    а `--check` сверял бы со сверкой и краснел бы вечно на верном состоянии.
    """
    root, tracker = repo
    _tree_left_behind(root, tracker / "own-otvechennyi.md",
                      _card_text("needs-owner", "отвеченный"),
                      _card_text("ingested", "отвеченный"))
    board = _load_builder()

    # 1. Доска собрана БЕЗ сверки и сама об этом говорит ⇒ сверка идёт по дереву, зелено.
    plain = board.render_board(board.collect_cards(tracker),
                               origin={"state": board.ORIGIN_UNMEASURED, "reason": "не запрашивалась"})
    board.atomic_write(tracker / "_BOARD.md", plain)
    assert board.board_built_with_origin_check(plain) is False
    assert board.board_drift(tracker, ref="origin/main") == []

    # 2. Доска собрана СО сверкой и говорит это ⇒ сверка тоже со сверкой, зелено.
    cards, verdict = board.resolve_against_origin(board.collect_cards(tracker), tracker,
                                                  ref="origin/main")
    checked = board.render_board(cards, origin=verdict)
    board.atomic_write(tracker / "_BOARD.md", checked)
    assert board.board_built_with_origin_check(checked) is True
    assert board.board_drift(tracker, ref="origin/main") == []


def test_old_board_without_the_line_is_not_called_drifted(repo) -> None:
    """Доска старого образца (строки вердикта нет) сверяется по ПРЕЖНИМ правилам.

    Обратный контроль к предыдущему: объявить её расходящейся значило бы покрасить
    сторожа в красный за то, что артефакт старше самой проверки, — и научить его гасить.
    """
    root, tracker = repo
    _tree_left_behind(root, tracker / "own-otvechennyi.md",
                      _card_text("needs-owner", "отвеченный"),
                      _card_text("ingested", "отвеченный"))
    board = _load_builder()
    old_style = "\n".join(l for l in board.render_board(board.collect_cards(tracker)).splitlines()
                           if "НЕ ИЗМЕРЕНА" not in l)
    board.atomic_write(tracker / "_BOARD.md", old_style)
    assert board.board_built_with_origin_check(old_style) is None
    assert board.board_drift(tracker, ref="origin/main") == []


def test_disabled_check_names_itself_in_the_header(repo) -> None:
    """`--no-origin-check` обязан НАЗВАТЬ себя в шапке, а не промолчать.

    Отсутствие строки читалось бы как «сверено и совпало» — ровно та неотличимость,
    ради которой вердикт заведён. Это же положительный контроль на проводку горячего
    пути: `_rebuild_board` зовёт сборщик именно с этим флагом.
    """
    root, tracker = repo
    (tracker / "own-a.md").write_text(_card_text("needs-owner", "вопрос"), encoding="utf-8")
    _commit_as_origin(root)
    board = _load_builder()
    board.TRACKER = tracker
    board.OUT = tracker / "_BOARD.md"
    assert board.main(["--no-origin-check", "--tracker-dir", str(tracker)]) == 0
    text = (tracker / "_BOARD.md").read_text(encoding="utf-8")
    assert "НЕ ИЗМЕРЕНА" in text and "не запрашивалась" in text, text[:600]


def test_card_mutation_does_not_pay_for_the_origin_check(tmp_path: Path) -> None:
    """ПРОВОДКА горячего пути: пересборка доски после мутации карточки идёт БЕЗ сверки.

    Это отдельный тест, а не следствие предыдущего. Мутация «убрать `--no-origin-check`
    из `_rebuild_board`» оставляла ЗЕЛЁНЫМИ все одиннадцать проверок выше: они меряют
    флаг, а не то, что его кто-то передаёт. Цена промаха измерима — сверка стоит ~84 с
    на живом трекере, и платил бы её КАЖДЫЙ ответ бота владельцу.

    Различить два «не измерено» позволяет ПРИЧИНА: у выключенной флагом сверки она своя,
    и подделать её нечем.
    """
    spec = importlib.util.spec_from_file_location(
        "_queue_cli_under_test", REPO_ROOT / "scripts" / "orchestrator_queue.py")
    assert spec and spec.loader
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    tracker = tmp_path / "tracker"
    tracker.mkdir()
    (tracker / "inbox-a.md").write_text(_card_text("new", "карточка"), encoding="utf-8")

    cli._rebuild_board(tracker_dir=tracker)

    text = (tracker / "_BOARD.md").read_text(encoding="utf-8")
    assert "не запрашивалась" in text, (
        "пересборка после мутации карточки обязана идти с --no-origin-check; "
        f"шапка доски: {text.splitlines()[:9]}")
