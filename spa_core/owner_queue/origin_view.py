#!/usr/bin/env python3
"""origin_view.py — карточки очереди в версии `origin/main`, без сети и без записи.

Зачем это вообще нужно
------------------------------------------------------------------------------
Очередь владельца живёт в файлах, но **дерево, из которого читает сторож, — не то
дерево, в которое пишут карточки**. Циклы работают в изолированных worktree и пушат
результат прямо на `origin` через Contents API, а автосинк прод-дерева возит только
`spa_core/` · `scripts/` · `tests/` — каталог `nimbalyst-local/tracker/` не возит
никто. Замер 17.08.2026 (цикл #270): в прод-дереве 416 карточек, на `origin/main` —
481, и **109 карточек прод-дереву не видны вовсе**.

Для любого сторожа, который читает очередь с диска, это означает ровно одно: его
ответ верен про КАТАЛОГ и неверен про ОЧЕРЕДЬ. Именно так `owner_decision_pending`
17.08 доложил `undelivered_count: 0` при живом вопросе владельцу `own-34`
(`needs-owner` на origin, файла в проде нет): вопрос был невидим в ОБЕ стороны —
ни в `pending` (файла нет), ни в `unchecked` (в журнале отправок его тоже нет,
потому что его ни разу не отправляли). Зелено по слепоте.

Что здесь есть и чего нет
------------------------------------------------------------------------------
Только ЧТЕНИЕ: `git ls-tree` + `git cat-file --batch` по локальной копии ref.
Ничего не пишет, не синхронизирует и **не ходит в сеть** — `git fetch` отсюда не
вызывается никогда (закреплено тестом). Значит и ответ здесь — про ТУ копию
`origin/main`, что уже лежит локально; поэтому `snapshot()` всегда возвращает её
sha, чтобы «сверено с origin» нельзя было прочитать как «сверено со свежайшим
origin».

**Разбор карточки не дублируется.** Тип и статус резолвит единственный писатель
этого правила — `queue.load_card_text` (он же `resolve_tracker_type`). Две копии
правила разбора и есть дефект, за который проект уже заплатил тремя невидимыми
вопросами владельца (#143–#145).

Своя тонкая обёртка над `git` здесь СОЗНАТЕЛЬНО, а не по недосмотру: у
`scripts/check_tracker_drift.py` есть тест-страж «сторож не ходит в сеть», который
подменяет ИМЕННО его `_git` и обязан видеть каждый его вызов. Утащить плумбинг в
общий модуль значило бы вывести часть вызовов из-под этого стража, то есть молча
ослабить проверку. Вместо этого у нового модуля свой такой же страж
(`test_origin_view.py`), а общим остаётся то, что и должно быть общим, — разбор.

Fail-CLOSED в форме «не измерено», а не тревоги
------------------------------------------------------------------------------
`Unmeasured` бросается, когда сверка НЕ ВЫПОЛНИЛАСЬ (нет git, ref не разрешается,
`ls-tree` вернул код). Отсутствие git-репозитория — законное состояние песочницы,
CI-фикстуры и чистой установки: там сверять просто не с чем, и звать это находкой
значило бы жечь предупреждение на пустом месте. Различать «нечего мерить» и
«померить не смогли» обязан ВЫЗЫВАЮЩИЙ — оба случая приходят сюда одним
исключением с причиной словами, и причина обязана доехать до отчёта.

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from spa_core.owner_queue.queue import load_card_text

#: С чем сверяемся по умолчанию. Локальная копия ref, без `fetch`.
DEFAULT_REF = "origin/main"
#: Путь каталога очереди внутри репозитория.
TRACKER_REL = "nimbalyst-local/tracker"

#: `_BOARD.md` лежит в том же каталоге, но карточкой не является: это ПРОИЗВОДНЫЙ
#: индекс, который регенерируется из того дерева, где выполнена команда, и потому
#: расходится всегда. Считать его карточкой — приучать читателя пролистывать вывод.
_NOT_CARDS = frozenset({"_BOARD"})

#: Разделитель `git cat-file --batch`: строка-заголовок `<sha> <type> <size>`,
#: затем ровно `size` байт содержимого и `\n`.
_BATCH_HEADER_PARTS = 3


class Unmeasured(RuntimeError):
    """Сверка с ref не выполнилась. Это «НЕ ИЗМЕРЕНО», а не «расхождений нет»."""


@dataclass(frozen=True)
class OriginCard:
    """Карточка в версии ref: ровно то, что нужно читателю очереди."""

    card_id: str
    tracker_type: str
    status: str
    title: str


def _git(root: Path, args: list[str], stdin_text: str | None = None) -> tuple[int, str]:
    """Локальный git. Сеть не задействуется ни одним из вызовов этого модуля."""
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированный argv, без shell
            ["git", "-C", str(root), *args],
            input=stdin_text, capture_output=True, text=True, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # git отсутствует / упал
        raise Unmeasured(f"git не выполнился ({' '.join(args[:2])}): {exc}") from exc
    return proc.returncode, proc.stdout


def repo_root_of(path: Path) -> Path:
    """Корень репозитория, которому принадлежит путь. Не репозиторий ⇒ Unmeasured."""
    probe = path if path.is_dir() else path.parent
    rc, out = _git(probe, ["rev-parse", "--show-toplevel"])
    if rc != 0 or not out.strip():
        raise Unmeasured(f"путь не принадлежит git-репозиторию: {path}")
    return Path(out.strip())


def ref_sha(root: Path, ref: str = DEFAULT_REF) -> str:
    """Sha локальной копии ref. Не разрешается ⇒ Unmeasured (сверять не с чем)."""
    rc, out = _git(root, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    if rc != 0 or not out.strip():
        raise Unmeasured(f"ref `{ref}` в этом репозитории не разрешается — сверять не с чем")
    return out.strip()


def snapshot(root: Path, ref: str = DEFAULT_REF,
             tracker_rel: str = TRACKER_REL) -> dict[str, str]:
    """{card_id: blob_sha} для `*.md` каталога очереди на ref."""
    rc, out = _git(root, ["ls-tree", "-r", ref, "--", tracker_rel])
    if rc != 0:
        raise Unmeasured(f"`git ls-tree {ref} -- {tracker_rel}` вернул код {rc}")
    found: dict[str, str] = {}
    for line in out.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 3 or parts[1] != "blob" or not path.endswith(".md"):
            continue
        stem = Path(path).stem
        if stem in _NOT_CARDS:
            continue
        found[stem] = parts[2]
    return found


def read_cards(root: Path, blobs: dict[str, str]) -> list[OriginCard]:
    """Разобрать карточки по их blob-sha — ОДНИМ процессом git на весь пакет.

    По sha, а не по `ref:path`: sha уже добыты `snapshot()`, и второй способ
    адресовать тот же объект — второй способ ошибиться. Пустой пакет процесс
    вообще не запускает: `cat-file --batch` с пустым stdin ждать нечего.

    Нечитаемый или неразобравшийся blob — Unmeasured с причиной, НЕ пропуск:
    молча выпавшая карточка и есть тот самый потерянный вопрос владельцу.
    """
    if not blobs:
        return []
    order = sorted(blobs)
    probe = "".join(f"{blobs[card_id]}\n" for card_id in order)
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированный argv, без shell
            ["git", "-C", str(root), "cat-file", "--batch"],
            input=probe.encode("utf-8"), capture_output=True, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Unmeasured(f"`git cat-file --batch` не выполнился: {exc}") from exc
    if proc.returncode != 0:
        raise Unmeasured(f"`git cat-file --batch` вернул код {proc.returncode}")

    cards: list[OriginCard] = []
    buf = proc.stdout
    pos = 0
    for card_id in order:
        nl = buf.find(b"\n", pos)
        if nl < 0:
            raise Unmeasured(f"ответ `git cat-file --batch` оборвался на {card_id}")
        header = buf[pos:nl].decode("utf-8", "replace").split()
        if len(header) != _BATCH_HEADER_PARTS or header[1] != "blob":
            raise Unmeasured(
                f"blob карточки {card_id} не прочитан: `{' '.join(header)}`")
        size = int(header[2])
        body = buf[nl + 1:nl + 1 + size]
        pos = nl + 1 + size + 1  # +1 — перевод строки после содержимого
        try:
            card = load_card_text(body.decode("utf-8"), f"{card_id}.md")
        except (UnicodeDecodeError, ValueError) as exc:
            raise Unmeasured(f"карточка {card_id} на ref не разобралась: {exc}") from exc
        cards.append(OriginCard(card_id=card_id, tracker_type=card.tracker_type or "",
                                status=(card.status or "").strip(),
                                title=card.title or card_id))
    return cards


def hidden_cards(tracker_dir: Path, *, ref: str = DEFAULT_REF,
                 tracker_type: str | None = None,
                 status: str | None = None) -> tuple[list[OriginCard], str]:
    """Карточки, которые есть на ref и которых НЕТ в этом дереве. → (карточки, sha ref).

    Фильтры `tracker_type`/`status` применяются к версии НА REF — другой версии
    у невидимой дереву карточки не существует по определению.

    Каталога дерева нет ⇒ Unmeasured: пустое множество здесь означало бы «дереву
    видно всё», а это ровно наоборот.
    """
    tdir = Path(tracker_dir)
    if not tdir.is_dir():
        raise Unmeasured(f"каталог очереди не существует или не каталог: {tdir}")
    root = repo_root_of(tdir)
    try:
        rel = tdir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise Unmeasured(f"каталог очереди вне своего репозитория: {tdir}") from exc

    sha = ref_sha(root, ref)
    origin = snapshot(root, ref, rel)
    in_tree = {p.stem for p in tdir.glob("*.md")} | _NOT_CARDS
    missing = {cid: blob for cid, blob in origin.items() if cid not in in_tree}

    cards = read_cards(root, missing)
    if tracker_type is not None:
        cards = [c for c in cards if c.tracker_type == tracker_type]
    if status is not None:
        cards = [c for c in cards if c.status == status]
    return cards, sha
