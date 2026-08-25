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

import re
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


def read_texts(root: Path, blobs: dict[str, str]) -> dict[str, str]:
    """{card_id: ИСХОДНЫЙ текст карточки} по blob-sha — ОДНИМ процессом git на пакет.

    Единственный в модуле читатель протокола `cat-file --batch`. Разбор кадров этого
    протокола (заголовок · ровно `size` байт · перевод строки) вынесен сюда не ради
    краткости: две копии такого разбора разошлись бы в том, какой обрыв ответа считать
    «не измерено», и один из читателей однажды молча потерял бы карточку.

    Нечитаемый blob — Unmeasured с причиной, НЕ пропуск: молча выпавшая карточка и есть
    тот самый потерянный вопрос владельцу.
    """
    if not blobs:
        return {}
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

    texts: dict[str, str] = {}
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
            texts[card_id] = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Unmeasured(f"карточка {card_id} на ref не читается: {exc}") from exc
    return texts


def read_cards(root: Path, blobs: dict[str, str]) -> list[OriginCard]:
    """Разобрать карточки по их blob-sha. Разбор — `queue.load_card_text`, один на репо.

    По sha, а не по `ref:path`: sha уже добыты `snapshot()`, и второй способ
    адресовать тот же объект — второй способ ошибиться.

    Неразобравшаяся карточка — Unmeasured с причиной, НЕ пропуск.
    """
    cards: list[OriginCard] = []
    for card_id, text in sorted(read_texts(root, blobs).items()):
        try:
            card = load_card_text(text, f"{card_id}.md")
        except ValueError as exc:
            raise Unmeasured(f"карточка {card_id} на ref не разобралась: {exc}") from exc
        cards.append(OriginCard(card_id=card_id, tracker_type=card.tracker_type or "",
                                status=(card.status or "").strip(),
                                title=card.title or card_id))
    return cards


def _locate(tracker_dir: Path, ref: str) -> tuple[Path, str, str]:
    """(корень репозитория, путь очереди внутри него, sha ref) — или Unmeasured.

    Общая преамбула обоих публичных запросов. Вынесена не ради краткости, а
    потому что это ОДНО решение «с чем мы вообще сверяемся»: две копии этой
    цепочки разошлись бы в том, какой случай считать неизмеримым, и один из
    двух читателей однажды получил бы молчание вместо причины.
    """
    tdir = Path(tracker_dir)
    if not tdir.is_dir():
        raise Unmeasured(f"каталог очереди не существует или не каталог: {tdir}")
    root = repo_root_of(tdir)
    try:
        rel = tdir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise Unmeasured(f"каталог очереди вне своего репозитория: {tdir}") from exc
    return root, rel, ref_sha(root, ref)


def cards_by_id(tracker_dir: Path, card_ids, *,
                ref: str = DEFAULT_REF) -> tuple[dict[str, OriginCard], str]:
    """Версии НАЗВАННЫХ карточек на ref. → ({card_id: карточка}, sha ref).

    Отвечает на вопрос, который `hidden_cards` не задаёт: «чем на самом деле
    кончилась ВОТ ЭТА карточка, которой в дереве нет». Дрейф прод↔origin возит
    только `spa_core/`·`scripts/`·`tests/`, поэтому «вопрос закрыт, а карточка
    просто не доехала» и «вопрос открыт и потерян» с диска выглядят одинаково —
    различает их ровно эта сверка.

    **Три исхода, и все три различимы:** карточка есть на ref ⇒ ключ в ответе со
    статусом · карточки нет и на ref ⇒ ключа НЕТ (это факт, а не сбой) · сверка
    не выполнилась ⇒ `Unmeasured` с причиной. Пустой ответ никогда не означает
    «всё хорошо».
    """
    root, rel, sha = _locate(Path(tracker_dir), ref)
    wanted = {str(c) for c in card_ids}
    if not wanted:
        # Спрашивать нечего — но sha назван всё равно: вызывающий обязан уметь
        # отличить «вопросов не было» от «сверка не состоялась».
        return {}, sha
    origin = snapshot(root, ref, rel)
    blobs = {cid: blob for cid, blob in origin.items() if cid in wanted}
    return {c.card_id: c for c in read_cards(root, blobs)}, sha


def card_sources(tracker_dir: Path, card_ids, *,
                 ref: str = DEFAULT_REF) -> tuple[dict[str, str], str]:
    """ИСХОДНЫЙ текст названных карточек в версии ref. → ({card_id: markdown}, sha ref).

    Зачем нужен текст, а не разобранная карточка: карточку, которой в дереве нет,
    нельзя ни показать владельцу, ни дать ему на неё ответить — весь путь ответа
    (`notify_needs_owner` → `materialize_card` → нажатие кнопки → `set_status`)
    работает с ФАЙЛОМ. Чтобы вопрос, живущий только на `origin`, дошёл до владельца
    целиком (с вариантами и рекомендацией из тела), его текст надо взять с ref
    дословно — а не пересказать по четырём полям `OriginCard`.

    Те же три различимых исхода, что у `cards_by_id`: есть на ref ⇒ ключ · нет ⇒
    ключа нет · сверка не выполнилась ⇒ `Unmeasured` с причиной.
    """
    root, rel, sha = _locate(Path(tracker_dir), ref)
    wanted = {str(c) for c in card_ids}
    if not wanted:
        return {}, sha
    origin = snapshot(root, ref, rel)
    blobs = {cid: blob for cid, blob in origin.items() if cid in wanted}
    return read_texts(root, blobs), sha


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
    root, rel, sha = _locate(tdir, ref)
    origin = snapshot(root, ref, rel)
    in_tree = {p.stem for p in tdir.glob("*.md")} | _NOT_CARDS
    missing = {cid: blob for cid, blob in origin.items() if cid not in in_tree}

    cards = read_cards(root, missing)
    if tracker_type is not None:
        cards = [c for c in cards if c.tracker_type == tracker_type]
    if status is not None:
        cards = [c for c in cards if c.status == status]
    return cards, sha


#: Пространство удалённых веток, в котором ищем вопросы владельца. Локальные копии
#: ref'ов, `git fetch` отсюда НЕ вызывается (общее правило модуля): ответ — про те
#: ветки, что уже лежат локально, и sha каждой печатается, чтобы «сверено с веткой»
#: нельзя было прочитать как «сверено со свежайшей веткой».
BRANCH_NAMESPACE = "refs/remotes/origin"


#: Метка решения «эту карточку с ветки мы прочитали и осознанно НЕ везём».
#: Пишется в ТЕЛО карточки-разбора на `origin/main` — там, где решение принимается,
#: а не в стороже. Строка видима в отрендеренном markdown НАМЕРЕННО: решение, которое
#: видно только парсеру, читатель отчёта проверить не может.
DROPPED_MARKER = "DROPPED-FROM-BRANCH:"

#: Дата решения — только `YYYY-MM-DD`. «Когда решили» либо есть, либо его нет:
#: свободная форма даты означала бы, что дату можно и не назвать.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Поля, без которых объявления НЕ существует. Ровно те три, которых потребовала
#: карточка `inbox-storozh-voprosy-vladeltsa-na-vetke-ne-zn` (автор · основание ·
#: дата) плюс имя самой карточки. `branch` необязателен: он уточняет, а не решает.
_DROPPED_REQUIRED = ("card", "by", "date", "reason")

#: Что снимается с НАЧАЛА строки перед тем, как спросить «это объявление?»: отступ,
#: markdown-маркер списка и цитата. Всё остальное перед меткой означает ПРОЗУ.
#:
#: Граница «код против прозы» здесь не педантизм, а замер: карточка, ОПИСЫВАЮЩАЯ этот
#: механизм, лежит в том же каталоге, который механизм читает, — и её фраза «строкой
#: `DROPPED-FROM-BRANCH:` в теле карточки-разбора» немедленно приехала в отчёт как
#: бракованное объявление (цикл #376, поймано своим же шагом 0-офис до пуша). Тот же
#: класс, что у сторожа, чей докстринг про `notify_channel` вносил это имя в корпус,
#: по которому сторож судил. Объявление — это СТРОКА, начинающаяся с метки; упоминание
#: метки внутри фразы — рассказ о механизме, а не его применение.
_DECL_PREFIX = re.compile(r"^[ \t]*(?:>[ \t]*)*(?:[-*+][ \t]+)?")


@dataclass(frozen=True)
class DroppedFromBranch:
    """Решение «карточка с ветки прочитана и осознанно НЕ везётся на базу».

    Третий исход рядом с «потеряно» и «убрано с базы» — и единственный, который
    нельзя измерить с диска: разбор ветки происходит в голове сессии, а на файловой
    системе выглядит ровно как потеря. Поэтому решение обязано быть ЗАПИСАНО, и
    записано с автором, датой и основанием: «решено не везти» без автора закрывает
    что угодно (тот же довод, что у `--dropped` шага 0a и у пятого вердикта
    уборщика деревьев, цикл #354).

    `declared_in` — карточка, в теле которой решение объявлено. Провенанс машинно,
    чтобы «кто это решил» не приходилось искать по журналам.
    """

    card_id: str
    by: str
    date: str
    reason: str
    branch: str
    declared_in: str


def parse_dropped_declarations(
        text: str, declared_in: str = "") -> tuple[list[DroppedFromBranch], list[tuple[str, str]]]:
    """Разобрать объявления `DROPPED-FROM-BRANCH:` в тексте ОДНОЙ карточки.

    → (объявления, брак). **Брак — это не пропуск.** Строка с меткой, но без автора,
    даты или основания, НЕ становится объявлением (карточка остаётся потерей) и при
    этом называется вслух: молча выброшенная строка означала бы, что автор решение
    записал, а сторож его не увидел, — и обе стороны считали бы, что всё в порядке.

    Формат — одна строка, поля `ключ=значение` через `;`, `reason` последний и
    забирает остаток строки (в основании законны и `;`, и `=`)::

        DROPPED-FROM-BRANCH: card=<id>; branch=<ветка>; by=<кто>; date=<YYYY-MM-DD>; reason=<текст>

    Разбор нарочно тупой и построчный: у него нет ни одного состояния, которое можно
    унаследовать от соседней строки, поэтому «объявление появилось само» невозможно.

    **Объявление — это строка, НАЧИНАЮЩАЯСЯ с метки** (допустим отступ, маркер списка,
    цитата). Метка внутри фразы — рассказ о механизме, а не его применение: иначе
    карточка, описывающая этот механизм, кормила бы своим текстом тот самый реестр,
    который механизм читает (см. `_DECL_PREFIX`).
    """
    found: list[DroppedFromBranch] = []
    broken: list[tuple[str, str]] = []
    where = declared_in or "<текст>"
    for lineno, raw in enumerate(str(text or "").splitlines(), start=1):
        start = _DECL_PREFIX.match(raw).end()
        if not raw.startswith(DROPPED_MARKER, start):
            continue
        tail = raw[start + len(DROPPED_MARKER):].strip()
        # `reason` забирает остаток строки: основание — свободный текст, и резать его
        # по разделителю значило бы терять ровно ту часть, ради которой поле и заведено.
        head, sep, reason = tail.partition("reason=")
        fields: dict[str, str] = {"reason": reason.strip() if sep else ""}
        for chunk in head.split(";"):
            key, eq, val = chunk.partition("=")
            if not eq:
                continue
            fields.setdefault(key.strip().lower(), val.strip())
        missing = [k for k in _DROPPED_REQUIRED if not fields.get(k)]
        if missing:
            broken.append((f"{where}:{lineno}",
                           "объявление без обязательн(ого/ых) пол(я/ей) "
                           f"{', '.join(missing)} — «решено не везти» без них неотличимо "
                           "от забывчивости, объявлением НЕ считается"))
            continue
        if not _ISO_DATE.match(fields["date"]):
            broken.append((f"{where}:{lineno}",
                           f"date={fields['date']!r} не в форме YYYY-MM-DD — "
                           "дата решения не прочитана, объявлением НЕ считается"))
            continue
        found.append(DroppedFromBranch(
            card_id=fields["card"], by=fields["by"], date=fields["date"],
            reason=fields["reason"], branch=fields.get("branch", ""),
            declared_in=declared_in))
    return found, broken


def _dropped_texts(root: Path, ref: str, rel: str, tracker_dir: Path) -> dict[str, str]:
    """Тексты карточек, в теле которых есть метка, — с ref И из живого дерева.

    Оба источника, потому что каждый в одиночку слеп в свою сторону: `nimbalyst-local/`
    не возит ни автосинк, ни CI-чекаут (урок #193), так что прод-дерево не видит
    объявления, сделанного другим циклом, а дерево CI не видит объявления, ещё не
    доехавшего на origin. Ключ — `card_id`; версия из дерева перекрывает версию с ref
    (она новее по построению — на ref карточка попадает позже).

    Отбор на ref — одним `git grep -l` по метке, а не чтением всех 600+ карточек:
    вопрос «где вообще есть метка» git отвечает дешевле, чем мы. Код 1 = совпадений
    нет (законный ответ), код >1 = сверка не выполнилась ⇒ `Unmeasured`.
    """
    rc, out = _git(root, ["grep", "--full-name", "-l", "-F", DROPPED_MARKER, ref, "--", rel])
    if rc > 1:
        raise Unmeasured(f"`git grep {DROPPED_MARKER} {ref}` вернул код {rc}")
    blobs: dict[str, str] = {}
    if rc == 0:
        paths = []
        for line in out.splitlines():
            _, _, path = line.partition(":")
            if path.endswith(".md") and Path(path).stem not in _NOT_CARDS:
                paths.append(path)
        if paths:
            on_ref = snapshot(root, ref, rel)
            blobs = {stem: sha for stem, sha in on_ref.items()
                     if stem in {Path(p).stem for p in paths}}
    texts = dict(read_texts(root, blobs))
    tdir = Path(tracker_dir)
    if tdir.is_dir():
        for path in sorted(tdir.glob("*.md")):
            if path.stem in _NOT_CARDS:
                continue
            try:
                body = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # нечитаемый файл дерева — не объявление; ref остаётся источником
            if DROPPED_MARKER in body:
                texts[path.stem] = body
    return texts


@dataclass(frozen=True)
class DroppedRegistry:
    """Что вообще объявлено «осознанно не везём» — и что при этом сломано.

    `by_card` — принятые объявления. `broken` — строки с меткой, которые объявлением
    не стали, с причиной СЛОВАМИ. `conflicts` — второе объявление о той же карточке
    с ДРУГИМ основанием: исход от этого не меняется (обе стороны говорят «не везём»),
    но два разных основания об одном решении — это расхождение, и молчать о нём
    значит выбрать одно из них за читателя.
    """

    by_card: dict[str, DroppedFromBranch]
    broken: tuple[tuple[str, str], ...]
    conflicts: tuple[tuple[str, str], ...]


def dropped_registry(tracker_dir: Path, *, base_ref: str = DEFAULT_REF) -> DroppedRegistry:
    """Реестр решений «прочитано и осознанно не везём». Не измеримо ⇒ `Unmeasured`.

    Пустой реестр — законный ответ («никто ничего не объявлял»), и он ОТЛИЧИМ от
    «посмотреть не смогли»: второе приходит исключением, как и везде в модуле.
    """
    root, rel, _sha = _locate(Path(tracker_dir), base_ref)
    texts = _dropped_texts(root, base_ref, rel, Path(tracker_dir))
    by_card: dict[str, DroppedFromBranch] = {}
    broken: list[tuple[str, str]] = []
    conflicts: list[tuple[str, str]] = []
    for declared_in in sorted(texts):
        try:
            card = load_card_text(texts[declared_in], f"{declared_in}.md")
        except ValueError as exc:
            broken.append((declared_in, f"карточка с меткой не разобралась: {exc}"))
            continue
        rows, bad = parse_dropped_declarations(card.body, declared_in)
        broken.extend(bad)
        for row in rows:
            prev = by_card.get(row.card_id)
            if prev is None:
                by_card[row.card_id] = row
            elif prev.reason != row.reason:
                conflicts.append((row.card_id,
                                  f"объявлено дважды с разным основанием: "
                                  f"`{prev.declared_in}` ({prev.by}, {prev.date}) против "
                                  f"`{row.declared_in}` ({row.by}, {row.date})"))
    return DroppedRegistry(by_card=by_card, broken=tuple(broken), conflicts=tuple(conflicts))


@dataclass(frozen=True)
class BranchCard:
    """Карточка, найденная на ветке и отсутствующая в канонической очереди.

    `branches` — все ветки, где карточка встретилась (одна и та же карточка живёт
    на нескольких ветках регулярно: ветка-потомок несёт карточку предка).

    `ever_on_base` различает ДВА разных факта, которые с диска выглядят одинаково:
    карточки на `origin/main` нет, потому что она туда никогда не попадала
    (потерянный вопрос), — и её там нет, потому что она **была и снята намеренно**
    (наш собственный тест-зонд `owner-decision-test-prizrak-ne-rozhdaetsya`, снятый
    коммитом `029627b46`). Признак измеримый, а не эвристический: история пути на
    базовом ref либо пуста, либо нет.

    `dropped` — ТРЕТИЙ факт, которого этим двум не хватало: карточку прочитали при
    разборе ветки и осознанно решили не везти (дубль уже разобранного, устаревшая
    премиса, замер приложен к карточке на базе). С диска это неотличимо от потери —
    на базе такая карточка не лежала НИКОГДА, — поэтому признак приходит не из
    файловой системы, а из ЗАПИСАННОГО решения (`DroppedFromBranch`). `None` значит
    «решения не записано», а не «решения не было»: незаписанное решение не считается.
    """

    card_id: str
    tracker_type: str
    status: str
    title: str
    branches: tuple[str, ...]
    ever_on_base: bool
    dropped: DroppedFromBranch | None = None


@dataclass(frozen=True)
class BranchScan:
    """Результат обхода веток. Пустой список карточек ≠ «не измерено».

    `unreadable` — ветки, которые прочитать не удалось, с причиной СЛОВАМИ. Одна
    нечитаемая ветка не отменяет замер по остальным, но и не имеет права исчезнуть:
    молча пропущенная ветка — это fail-OPEN внутри fail-CLOSED-сверки.
    """

    base_ref: str
    base_sha: str
    branches_read: tuple[str, ...]
    unreadable: tuple[tuple[str, str], ...]
    cards: tuple[BranchCard, ...]
    #: Строки с меткой «не везём», которые объявлением НЕ стали (нет автора / даты /
    #: основания), и объявления, названные дважды с разным основанием. Пустой кортеж —
    #: это «брака нет», а не «не смотрели»: сам разбор либо состоялся, либо бросил.
    dropped_broken: tuple[tuple[str, str], ...] = ()
    #: Объявления о карточках, которых на ветках НЕТ. Решение пережило свой предмет
    #: (ветку удалили, карточку всё-таки привезли) — не находка, но и не молчание:
    #: реестр, из которого ничего никогда не уходит, через год состоит из мусора.
    dropped_stale: tuple[str, ...] = ()


def remote_branches(root: Path, *, namespace: str = BRANCH_NAMESPACE,
                    base_ref: str = DEFAULT_REF) -> list[str]:
    """Короткие имена удалённых веток пространства, КРОМЕ базовой и `HEAD`.

    `origin/HEAD` — символическая ссылка на ту же базу; считать её веткой значило бы
    сверять базу с самой собой и получать вечный ноль, неотличимый от честного.
    """
    rc, out = _git(root, ["for-each-ref", "--format=%(refname:short)", namespace])
    if rc != 0:
        raise Unmeasured(f"`git for-each-ref {namespace}` вернул код {rc}")
    skip = {base_ref, f"{namespace.rsplit('/', 1)[-1]}/HEAD", "origin/HEAD"}
    return [b for b in (line.strip() for line in out.splitlines()) if b and b not in skip]


def path_ever_on_ref(root: Path, ref: str, path: str) -> bool:
    """Встречался ли путь в истории ref хоть раз. Не измеримо ⇒ Unmeasured.

    Отвечает ровно на «была ли карточка в канонической очереди когда-либо», и
    ответ этот с текущего снимка неполучаем: снимок знает только «сейчас».
    """
    rc, out = _git(root, ["log", "--format=%H", "-1", ref, "--", path])
    if rc != 0:
        raise Unmeasured(f"`git log {ref} -- {path}` вернул код {rc}")
    return bool(out.strip())


def branch_only_cards(tracker_dir: Path, *, base_ref: str = DEFAULT_REF,
                      namespace: str = BRANCH_NAMESPACE,
                      tracker_type: str | None = None,
                      status: str | None = None) -> BranchScan:
    """Карточки, которых нет НИ в этом дереве, НИ на базовом ref — только на ветках.

    Третье плечо класса «вопрос владельцу невидим», и самое немое из трёх. Первые
    два уже измеряются: «есть на `origin/main`, нет в дереве» (`hidden_cards`,
    читатель — `owner_decision_pending`) и «есть в дереве, нет на origin» (дрейф
    прод↔origin). Карточка, живущая ТОЛЬКО на ветке, невидима обеим сверкам сразу:
    ни очередь, ни отправитель (`resend.open_questions` читает дерево + `origin/main`)
    её не встретят никогда, а значит вопрос нельзя ни задать, ни закрыть.

    Замер 23.08.2026 (цикл #351): 18 таких `needs-owner` на 36 ветках, из них
    `own-2026-08-22-snyat-changelog-so-saita` лежит внутри ОТКРЫТОГО PR #35 и просит
    подпись владельца, без которой этот же PR не вливают, — замкнутый круг, который
    сам не разомкнётся.

    Фильтры применяются к версии НА ВЕТКЕ: другой версии у такой карточки нет.
    Дерево исключается наравне с базой намеренно — карточка, лежащая в живом дереве,
    владельцу достижима, и это плечо меряет не эта функция.

    Fail-CLOSED: базу не прочитать ⇒ `Unmeasured` (пустой ответ означал бы «на ветках
    ничего нет»). Отдельная ветка не прочиталась ⇒ она названа в `unreadable`, а
    замер по остальным состоялся.

    К каждой найденной карточке прикладывается решение «прочитано и осознанно не
    везём», если оно ЗАПИСАНО (`dropped_registry`). Отбор карточек это НЕ меняет:
    объявление ничего не прячет, оно называет исход. Считать ли объявленную карточку
    находкой — решает читатель (`owner_decision_pending._scan_branch_queue`), и
    именно поэтому она остаётся в `cards`, а не выпадает из ответа: строка, которая
    исчезла, проверке не поддаётся.
    """
    tdir = Path(tracker_dir)
    root, rel, base_sha = _locate(tdir, base_ref)
    base = snapshot(root, base_ref, rel)
    in_tree = {p.stem for p in tdir.glob("*.md")} | _NOT_CARDS
    known = set(base) | in_tree

    read: list[str] = []
    unreadable: list[tuple[str, str]] = []
    found: dict[str, tuple[OriginCard, list[str]]] = {}
    for branch in remote_branches(root, namespace=namespace, base_ref=base_ref):
        try:
            extra = {cid: blob for cid, blob in snapshot(root, branch, rel).items()
                     if cid not in known}
            cards = read_cards(root, extra)
        except Unmeasured as exc:
            unreadable.append((branch, str(exc)))
            continue
        read.append(branch)
        for card in cards:
            if tracker_type is not None and card.tracker_type != tracker_type:
                continue
            if status is not None and card.status != status:
                continue
            found.setdefault(card.card_id, (card, []))[1].append(branch)

    try:
        registry = dropped_registry(tdir, base_ref=base_ref)
    except Unmeasured as exc:
        # Реестр не прочитался — «осознанно не везём» утверждать нечем ни про одну
        # карточку. Fail-CLOSED в сторону НАХОДКИ (как и у `ever_on_base` ниже):
        # лишний раз назвать разобранную дешевле, чем промолчать о потерянной.
        registry = DroppedRegistry(by_card={}, broken=((f"{base_ref}:реестр", str(exc)),),
                                   conflicts=())

    out: list[BranchCard] = []
    for card_id, (card, branches) in sorted(found.items()):
        try:
            ever = path_ever_on_ref(root, base_ref, f"{rel}/{card_id}.md")
        except Unmeasured as exc:
            # История пути не прочиталась — «намеренно снята» утверждать нечем.
            # Fail-CLOSED в сторону НАХОДКИ: пропустить потерянный вопрос дороже,
            # чем лишний раз назвать снятый. Причина уезжает в `unreadable`.
            unreadable.append((f"{base_ref}:{card_id}", str(exc)))
            ever = False
        out.append(BranchCard(card_id=card.card_id, tracker_type=card.tracker_type,
                              status=card.status, title=card.title,
                              branches=tuple(branches), ever_on_base=ever,
                              dropped=registry.by_card.get(card.card_id)))
    # Объявление, у которого не нашлось предмета: карточки нет ни на одной прочитанной
    # ветке. Считается ТОЛЬКО по тем веткам, что прочитались, — иначе нечитаемая ветка
    # превращала бы живое объявление в «протухшее» (fail-OPEN в отчёте о чистоте).
    stale = tuple(sorted(cid for cid in registry.by_card if cid not in found)) if not unreadable else ()
    return BranchScan(base_ref=base_ref, base_sha=base_sha,
                      branches_read=tuple(read), unreadable=tuple(unreadable),
                      cards=tuple(out),
                      dropped_broken=tuple(registry.broken) + tuple(
                          (cid, why) for cid, why in registry.conflicts),
                      dropped_stale=stale)
