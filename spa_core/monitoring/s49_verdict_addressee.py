"""Адресат вердикта `НЕ ВЫПОЛНЕН` у критерия §49 приказа владельца «Portfolio CIO».

Заказ G95 п. 3 (хвост ADR-507) дословно:

    «Вердикт `not_satisfied` у критерия владельца обязан иметь адресата — и
     здесь он УЖЕ есть. <…> Остаток заказа поэтому другой: **сводка §49 обязана
     НАЗЫВАТЬ адресата вердикта**, чтобы „НЕ ВЫПОЛНЕН“ нельзя было прочесть как
     „агент не доделал“, когда починка лежит за предметом №1 границы. Сегодня
     связи „критерий → открытая карточка владельца“ нет ни в одном поле, и её
     отсутствие неотличимо от „адресата нет“.»

## Что здесь не так без прибора

Замер сводки 2026-10-04 (ADR-553): `ВЫПОЛНЕНО 1 · НЕ ВЫПОЛНЕНО 9 · НЕ ИЗМЕРЕНО 3`.
Девять строк `❌ НЕ ВЫПОЛНЕН` — и ни одна не говорит, КТО вправе это починить.
Читатель (в том числе владелец) читает девять одинаковых отказов как девять
одинаковых недоделок агента. А это неверно: починка `Economics` лежит в
аллокаторе, то есть на денежном пути — **предмет №1** границы ADR-285, и
вопрос об этом уже стои́т в очереди (`own-optimum-proigryvaet-resheniyu-nichego-ne-d`
от 27.09). Разница между «агент не доделал» и «вопрос задан, ответа нет»
принципиальна: первое чинится работой, второе — решением владельца, и слить их
в один значок значит скрыть решение под видом задолженности.

## Где прибор берёт привязку «критерий → карточка»

**Не у себя и не у пробы — у САМОЙ КАРТОЧКИ.** Это выбор, и у него причина.

Привязку можно было объявить рядом с `s49_criterion` у пробы (так сделаны
ADR-507/508). Но адресат — свойство ОЧЕРЕДИ, а не измерительного прибора, и
главное: он МЕНЯЕТСЯ в тот момент, когда владелец отвечает, а проба в этот
момент не меняется ни на байт. Указатель, живущий в коде, молча расходится с
состоянием очереди — ровно класс ADR-220. Указатель, живущий в карточке,
пережить её не может по построению.

Поэтому карточка объявляет сама:

    s49_criteria: Economics

Форма **плоская и через запятую** намеренно. Канонический разбор frontmatter
(`spa_core.owner_queue.queue._parse_frontmatter`) — минимальный и список YAML
(`- Economics` под ключом) НЕ разбирает: ключ с пустым значением он читает как
начало вложенного блока, а строку без двоеточия пропускает, и объявление
исчезает БЕЗ ЕДИНОГО СЛОВА. Это дефект того же класса, против которого написан
весь прибор, поэтому он **измеряется, а не обходится**: блочная форма ключа —
третий исход `DROPPED_FORM` с названной причиной, а не «объявления нет»
(см. :data:`BLOCK_FORM_RE`).

Запятая как разделитель — не допущение: имена критериев §49 разбираются
`cio_acceptance_rollup._HEADING_RE`, который запятую не пропускает вовсе. Прибор
это ПРОВЕРЯЕТ у переданного населения и отказывает, если имя с запятой всё же
пришло: иначе разделитель стал бы неоднозначен молча.

## Очередь, о которой идёт речь, — та, что доходит до владельца

`nimbalyst-local/` в прод-дерево не синхронизируется (ADR-152), циклы правят
карточки в изолированных worktree и пушат на `origin`. Значит «очередь» — это
`origin/main`, и авторитет здесь у ref, а не у каталога под рукой
(`spa_core.owner_queue.origin_view` — тот же читатель, что у сторожа дрейфа;
второй копии разбора карточки не появляется, его делает единственный писатель
правила `queue.load_card_text`).

Каталог дерева читается ВТОРОЙ осью и даёт **собственную находку**:
объявление, лежащее только в рабочем дереве, не названо владельцу НИКОМУ —
дословно «доставлено ≠ работает» из `.claude/rules/deployment.md`. Такое
объявление не имеет права считаться адресатом, и исход для него свой
(`TREE_ONLY`). Расхождение дерева с ref здесь поэтому НЕ «не измерено»: для
очереди оно штатно, и объявить его неизмеримым значило бы потерять состоявшееся
наблюдение.

## Пять исходов, и каждый читается по-разному

====================  =========================================================
`OWNER_OPEN`          объявление есть на ref, карточка типа `owner-decision`, и
                      её статус ОТКРЫТ ⇒ адресат назван: вопрос стои́т, ответа
                      нет. «НЕ ВЫПОЛНЕН» здесь не задолженность агента
`OWNER_CLOSED`        объявление есть, но все объявившие карточки ЗАКРЫТЫ ⇒
                      находка: вердикт говорит «не выполнено», а вопрос уже
                      отвечен — ответ не исполнен или вопрос надо задать заново
`TREE_ONLY`           объявление живёт только в рабочем дереве, на ref его нет ⇒
                      владельцу адресат НЕ НАЗВАН; доставка не состоялась
`OUTSIDE_QUEUE`       объявление несёт карточка НЕ владельческого типа ⇒ адресат
                      не владелец; для вопроса «за кем это решение» ответа нет
`NONE`                объявления нет ни у одной карточки ⇒ адресат НЕ НАЗВАН.
                      Это сегодняшнее состояние всех девяти, и оно обязано быть
                      видно числом, а не отсутствием столбца
====================  =========================================================

Шестой исход — `UNMEASURED` — отдельным полем отчёта (`problem`), а не строкой
критерия: он про то, что очередь не прочитана ВОВСЕ, и про критерии при этом не
сказано ничего.

Порядок разрешения: **открытая карточка на ref доминирует**. Критерий, у
которого есть и открытая карточка на ref, и черновик в дереве, адресата имеет —
находка о недоставленном черновике при этом не теряется, она печатается рядом
(`tree_only_extra`).

## Чего прибор НЕ докладывает (назвать слепоту — часть замера)

* **Верность привязки.** Что карточка ДЕЙСТВИТЕЛЬНО излагает этот критерий —
  утверждение её автора. Прибор читает поле, а не смысл текста; совпадение по
  словам он не ищет вовсе (подстрочный поиск и был бы догадкой, ADR-333).
* **Полноту очереди.** О карточке, которой нет ни в дереве, ни на ref, он не
  знает ничего.
* **Нужен ли адресат вообще.** Критерий, который агент вправе починить сам,
  адресата владельца не требует, и `NONE` у него — не находка. Разделить это
  может только предмет границы (ADR-285), а он объявлен прозой; прибор печатает
  исход и не судит о его цене.

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import re
from pathlib import Path

from spa_core.owner_queue import origin_view
from spa_core.owner_queue.queue import CARD_STATUSES, _OPEN_STATUSES, load_card_text

#: Поле карточки, которым она объявляет себя адресатом критериев §49. Одно имя,
#: один разделитель; второе имя было бы вторым местом для той же привязки.
FIELD = "s49_criteria"

#: Разделитель перечня. Запятая безопасна ПО ЗАМЕРУ населения, а не по вере:
#: заголовок критерия §49 запятую не содержит (разбор раздела её не пропускает).
#: Условие проверяется у переданного населения — см. :func:`measure`.
SEPARATOR = ","

#: Ключ, записанный БЛОЧНОЙ формой (`s49_criteria:` и список под ним). Канонический
#: разбор frontmatter такое объявление отбрасывает молча, поэтому форма ловится
#: ОТДЕЛЬНО и становится третьим исходом. Это НЕ второй разбор карточки: вопрос
#: здесь ровно один — «присутствует ли ключ, чьё значение разбор потерял».
BLOCK_FORM_RE = re.compile(rf"^{FIELD}\s*:\s*$", re.MULTILINE)

#: Тип карточки, чей статус и есть ответ на «ждёт ли владелец».
OWNER_TYPE = "owner-decision"

OWNER_OPEN = "OWNER_OPEN"
OWNER_CLOSED = "OWNER_CLOSED"
TREE_ONLY = "TREE_ONLY"
OUTSIDE_QUEUE = "OUTSIDE_QUEUE"
NONE = "NONE"

#: Человекочитаемый исход — ОДНОЙ строкой, для печати рядом со строкой критерия.
KIND_RU = {
    OWNER_OPEN: "адресат назван: вопрос владельцу стои́т, ответа нет",
    OWNER_CLOSED: "объявившая карточка ЗАКРЫТА — вердикт спорит с отвеченным вопросом",
    TREE_ONLY: "объявление живёт только в рабочем дереве — владельцу НЕ НАЗВАНО",
    OUTSIDE_QUEUE: "объявление несёт карточка НЕ владельческого типа — адресат не владелец",
    NONE: "адресат НЕ НАЗВАН ни одной карточкой",
}


class Unmeasured(Exception):
    """Очередь не прочитана. Это «НЕ ИЗМЕРЕНО», а не «адресата нет»."""


class Declaration:
    """Объявление одной карточки: кто она, в каком статусе и что объявила."""

    __slots__ = ("card_id", "tracker_type", "status", "title", "criteria")

    def __init__(self, card_id: str, tracker_type: str, status: str, title: str,
                 criteria: tuple[str, ...]):
        self.card_id = card_id
        self.tracker_type = tracker_type
        self.status = status
        self.title = title
        self.criteria = criteria

    def as_dict(self) -> dict:
        return {"card": self.card_id, "type": self.tracker_type,
                "status": self.status, "title": self.title,
                "criteria": list(self.criteria), "open": self.is_open()}

    def is_open(self) -> bool | None:
        """Открыт ли вопрос. `None` — статус вне объявленной словарности.

        Третий исход здесь обязателен: статус-опечатка («closed») делает
        карточку невидимой любому фильтру, и прочесть её как ЗАКРЫТУЮ значило бы
        молча снять вопрос владельца. Словарность одна — `queue.CARD_STATUSES`.
        """
        if self.status not in CARD_STATUSES:
            return None
        return self.status in _OPEN_STATUSES


def parse_declaration(text: str, card_id: str) -> tuple[Declaration | None, str | None]:
    """Разобрать объявление одной карточки. Возврат — (объявление, причина-отказ).

    Обе половины возврата могут быть пусты одновременно: карточка, не объявившая
    поля вовсе, — это не отказ, а штатное молчание.
    """
    try:
        card = load_card_text(text, f"{card_id}.md")
    except (ValueError, TypeError) as exc:
        return None, f"карточка {card_id} не разобралась: {exc}"

    raw = card.fields.get(FIELD)
    if raw is None or str(raw).strip() == "":
        # Ключ есть, а значения канонический разбор не отдал — ровно блочная
        # форма. Молчать о ней нельзя: «объявления нет» и «объявление потеряно
        # разбором» чинятся разным (инв. #17).
        if BLOCK_FORM_RE.search(text):
            return None, (
                f"карточка {card_id}: поле `{FIELD}` объявлено БЛОЧНОЙ формой — "
                f"канонический разбор frontmatter её отбрасывает, объявление "
                f"потеряно; записать плоским перечнем через «{SEPARATOR}»")
        return None, None

    names = tuple(part.strip() for part in str(raw).split(SEPARATOR) if part.strip())
    if not names:
        return None, (f"карточка {card_id}: поле `{FIELD}` есть, но ни одного имени "
                      f"критерия из него не разобрано ({raw!r})")
    return Declaration(card_id=card_id, tracker_type=card.tracker_type or "",
                       status=(card.status or "").strip(),
                       title=card.title or card_id, criteria=names), None


def _declarations_from_texts(texts: dict[str, str]) -> tuple[list[Declaration], list[str]]:
    found: list[Declaration] = []
    problems: list[str] = []
    for card_id in sorted(texts):
        decl, problem = parse_declaration(texts[card_id], card_id)
        if problem:
            problems.append(problem)
        if decl is not None:
            found.append(decl)
    return found, problems


def read_ref(tracker_dir, ref: str) -> tuple[list[Declaration], list[str], str]:
    """Объявления в версии `ref` — авторитетная очередь. Бросает :class:`Unmeasured`."""
    tdir = Path(tracker_dir)
    root = origin_view.repo_root_of(tdir)
    sha = origin_view.ref_sha(root, ref)
    try:
        rel = tdir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise Unmeasured(f"каталог очереди вне своего репозитория: {tdir}") from exc
    blobs = origin_view.snapshot(root, ref, rel)
    if not blobs:
        raise Unmeasured(f"на `{ref}` ({sha[:9]}) в {rel} нет НИ ОДНОЙ карточки — "
                         f"очередь пуста по построению, и пустая очередь зелена "
                         f"сама собой")
    texts = origin_view.read_texts(root, blobs)
    decls, problems = _declarations_from_texts(texts)
    return decls, problems, sha


def read_tree(tracker_dir) -> tuple[list[Declaration], list[str]]:
    """Объявления в рабочем дереве — ВТОРАЯ ось, не авторитет."""
    tdir = Path(tracker_dir)
    if not tdir.is_dir():
        return [], [f"каталога очереди {tdir} нет — вторая ось не измерена"]
    texts: dict[str, str] = {}
    problems: list[str] = []
    for path in sorted(tdir.glob("*.md")):
        if path.stem in origin_view._NOT_CARDS:
            continue
        try:
            texts[path.stem] = path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"карточка {path.name} в дереве не прочитана: {exc}")
    decls, more = _declarations_from_texts(texts)
    return decls, problems + more


def _index(decls: list[Declaration]) -> dict[str, list[Declaration]]:
    by_criterion: dict[str, list[Declaration]] = {}
    for decl in decls:
        for name in decl.criteria:
            by_criterion.setdefault(name, []).append(decl)
    return by_criterion


def measure(criteria, *, tracker_dir, ref: str = origin_view.DEFAULT_REF) -> dict:
    """Назвать адресата у каждого критерия населения.

    `criteria` — население §49 В ПОРЯДКЕ ТЗ (его меряет сводка, не этот прибор:
    второе население было бы вторым местом для того же числа).
    """
    names = list(criteria)
    bad = [n for n in names if SEPARATOR in n]
    if bad:
        raise Unmeasured(
            f"имя критерия содержит разделитель «{SEPARATOR}» ({', '.join(bad)!s}) — "
            f"перечень в поле `{FIELD}` стал бы неоднозначен, и прибор молча "
            f"приписал бы объявление не тому критерию")

    try:
        ref_decls, ref_problems, sha = read_ref(tracker_dir, ref)
    except origin_view.Unmeasured as exc:
        raise Unmeasured(f"очередь на `{ref}` не прочитана: {exc}") from exc
    tree_decls, tree_problems = read_tree(tracker_dir)

    by_ref = _index(ref_decls)
    by_tree = _index(tree_decls)

    rows = []
    for name in names:
        on_ref = by_ref.get(name) or []
        in_tree = by_tree.get(name) or []
        owner_on_ref = [d for d in on_ref if d.tracker_type == OWNER_TYPE]
        open_owner = [d for d in owner_on_ref if d.is_open() is True]
        unknown = [d for d in owner_on_ref if d.is_open() is None]
        # Объявление, существующее только в дереве: сравниваются ИМЕНА карточек,
        # а не их число — карточка, правленная в дереве и уже лежащая на ref,
        # недоставленным объявлением не является.
        tree_only = [d for d in in_tree if d.card_id not in {x.card_id for x in on_ref}]

        if open_owner:
            kind = OWNER_OPEN
        elif owner_on_ref:
            kind = OWNER_CLOSED
        elif on_ref:
            kind = OUTSIDE_QUEUE
        elif tree_only:
            kind = TREE_ONLY
        else:
            kind = NONE

        rows.append({
            "criterion": name,
            "kind": kind,
            "detail": KIND_RU[kind],
            "cards": [d.as_dict() for d in (open_owner or owner_on_ref or on_ref
                                            or tree_only)],
            # Недоставленный черновик НЕ исчезает из отчёта оттого, что адресат
            # уже назван на ref: это отдельное наблюдение и печатается рядом.
            "tree_only_extra": [d.card_id for d in tree_only] if kind != TREE_ONLY else [],
            "unknown_status": [d.as_dict() for d in unknown],
        })

    counts: dict[str, int] = {k: 0 for k in KIND_RU}
    for row in rows:
        counts[row["kind"]] += 1

    orphan = {name: sorted(d.card_id for d in decls)
              for name, decls in sorted(by_ref.items()) if name not in names}

    return {
        "rows": rows,
        "counts": counts,
        "ref": ref,
        "ref_sha": sha,
        "tracker_dir": str(tracker_dir),
        "cards_declaring_on_ref": len(ref_decls),
        "cards_declaring_in_tree": len(tree_decls),
        "orphan_declarations": orphan,
        "problems": ref_problems + tree_problems,
    }
