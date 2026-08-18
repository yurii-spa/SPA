#!/usr/bin/env python3
"""delivery_gate.py — можно ли закрывать карточку: её работа УЖЕ на `origin/main`?

Какой дефект это закрывает
------------------------------------------------------------------------------
Класс «осиротевшая работа»: сессия умирает МЕЖДУ работой и пушем, результат
остаётся только в её дереве, а карточка при этом уже переведена в `done`. Дальше
работает не отсутствие работы, а именно закрытая карточка: следующая сессия
читает доску, видит `done` и не берёт задачу. Работа считается сделанной, на
origin её нет, и узнаётся это только случайной сверкой.

Замер по журналу `data/tracker_status_audit.jsonl` этого дерева (13–18.08.2026):
**десять** переходов `→ done`, и ни один из них не виден на `origin/main` —
шесть карточек там до сих пор `new`, одна `backlog`, одной нет вовсе. Закрытие
карточки — локальная запись в файл; доставка — отдельное событие позже; ничто
их не связывало.

Что здесь измеряется — и чего здесь НЕТ
------------------------------------------------------------------------------
Измеряется ОДНА вещь, зато без гаданий: **расходится ли эта карточка с её
версией на `origin/main`**. Тело карточки — это и есть приёмка (CLAUDE.md §3:
что сделано, чем проверено); если тело в дереве богаче, чем на origin, значит
работа этой карточки в дереве ЕСТЬ, а на origin её нет — и звать её `done`
рано.

Чего здесь сознательно нет:

* **разбора прозы.** Сканировать тело в поисках имён файлов пробовали: из 42
  найденных имён 38 не существовало НИГДЕ — карточки называют файлы, которые
  обсуждают, а не только те, что доставляют. Гейт на таком разборе отказывал бы
  непредсказуемо, а непредсказуемый сторож выключают;
* **проверки всего дерева.** «В дереве нет недоставленного» — мера слишком
  грубая: в живом дереве 18.08 расходились с локальной копией `origin/main`
  475 путей вне трекера (ref отстаёт на 30 коммитов, пуш идёт в origin через
  API мимо локального ref). Такой гейт отказывал бы ВСЕГДА, то есть был бы
  запретом закрывать карточки;
* **сети.** Сверка идёт через `origin_view` — та же локальная копия ref,
  никакого `fetch` (закреплено тестом). Поэтому вердикт всегда называет sha
  ref: «работа не на origin» здесь означает «нет в ЭТОЙ копии origin/main», и
  если работа только что отправлена, лечится это `git fetch origin main` на
  стороне вызывающего, а не сетевым вызовом изнутри сторожа.

Три исхода, и все три различимы
------------------------------------------------------------------------------
* `DELIVERED` — карточка на ref и совпадает ⇒ закрывать можно;
* `ABSENT_ON_REF` — карточки на ref нет вовсе ⇒ закрывать можно. Не поблажка:
  такой карточки на origin нет целиком, значит `done` и тело уедут ОДНИМ
  файлом — origin физически не может показать «закрыто» без содержимого;
* `UNDELIVERED` — карточка на ref есть и отличается ⇒ отказ.

Служебные строки из сверки исключены (`status`, `claimed_by`, `claimed_at`):
захват карточки и сам переход статуса — бухгалтерия инструмента, а не работа.
Без этого исключения гейт краснел бы на КАЖДОЙ захваченной карточке, то есть
на всех, взятых по протоколу, — и был бы выключен в первый же день.

`Unmeasured` (нет git, ref не разрешается) — это «НЕ ИЗМЕРЕНО», а не «чисто».
Различать «нечего мерить» и «померить не смогли» обязан вызывающий, как и в
`origin_view`; отказывать в закрытии карточки из-за отсутствия git-репозитория
(песочница, CI-фикстура) значило бы менять потерю следа на потерю работы.

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from spa_core.owner_queue.origin_view import (
    DEFAULT_REF,
    Unmeasured,
    _git,
    ref_sha,
    repo_root_of,
    snapshot,
)

__all__ = [
    "ABSENT_ON_REF",
    "BOOKKEEPING_KEYS",
    "CloseVerdict",
    "DELIVERED",
    "DEFAULT_REF",
    "UNDELIVERED",
    "Unmeasured",
    "check_card_delivered",
    "normalized_card",
]

#: Верхнеуровневые ключи frontmatter, которые НЕ являются работой карточки.
#: `status` — то, что мы сейчас и собираемся менять; `claimed_by`/`claimed_at`
#: пишет и снимает захват (`scripts/check_card_claim.py`), к содержанию работы
#: они отношения не имеют.
BOOKKEEPING_KEYS = frozenset({"status", "claimed_by", "claimed_at"})

DELIVERED = "delivered"
ABSENT_ON_REF = "absent-on-ref"
UNDELIVERED = "undelivered"


@dataclass(frozen=True)
class CloseVerdict:
    """Вердикт гейта. `allowed=False` — закрывать нельзя, причина словами."""

    code: str
    allowed: bool
    detail: str
    ref: str
    ref_sha: str

    @property
    def measured(self) -> bool:
        """Сверка состоялась. `Unmeasured` сюда не доходит — он исключение."""
        return True


def normalized_card(text: str) -> str:
    """Текст карточки без служебных строк frontmatter — то, что и есть работа.

    Сравнивать сырые байты нельзя: захват карточки дописывает `claimed_by` /
    `claimed_at`, и любая взятая по протоколу карточка расходилась бы с origin
    ещё до того, как по ней сделана хоть строчка. Исключается ровно
    `BOOKKEEPING_KEYS` и ничего сверх: тело не трогается вовсе.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text.strip()
    for i in range(1, len(lines)):
        if lines[i].strip() != "---":
            continue
        kept = []
        for ln in lines[1:i]:
            key = ln.split(":", 1)[0].strip()
            # Только верхний уровень: вложенные строки (`  type: inbox`) начинаются
            # с пробела и служебными ключами не считаются никогда.
            if not ln[:1].isspace() and key in BOOKKEEPING_KEYS:
                continue
            kept.append(ln.rstrip())
        return "\n".join(["---", *kept, "---", *(l.rstrip() for l in lines[i + 1:])]).strip()
    return text.strip()  # незакрытый frontmatter — сравниваем как есть


def _card_text_on_ref(root: Path, card_path: Path, ref: str) -> str | None:
    """Текст этой карточки на ref, или None — если её там нет.

    Список карточек берёт `origin_view.snapshot()` (тот же и единственный
    читатель дерева ref), содержимое — `git cat-file` по добытому им blob-sha:
    второй способ адресовать тот же объект был бы вторым способом ошибиться.
    """
    try:
        rel = card_path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise Unmeasured(f"карточка вне своего репозитория: {card_path}") from exc
    blobs = snapshot(root, ref, rel.parent.as_posix())
    blob = blobs.get(card_path.stem)
    if blob is None:
        return None
    rc, out = _git(root, ["cat-file", "-p", blob])
    if rc != 0:
        raise Unmeasured(f"`git cat-file -p {blob[:9]}` вернул код {rc}")
    return out


def check_card_delivered(card_path: str | Path, *, ref: str = DEFAULT_REF) -> CloseVerdict:
    """Можно ли закрывать эту карточку: её работа уже в версии ref?

    Сверка не выполнилась ⇒ `Unmeasured` с причиной (это НЕ «чисто»).
    """
    p = Path(card_path)
    try:
        local = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise Unmeasured(f"карточка не прочитана: {exc}") from exc

    root = repo_root_of(p)
    sha = ref_sha(root, ref)
    on_ref = _card_text_on_ref(root, p, ref)
    if on_ref is None:
        return CloseVerdict(
            code=ABSENT_ON_REF, allowed=True, ref=ref, ref_sha=sha,
            detail=(f"карточки нет на {ref} ({sha[:9]}) — статус и тело уедут одним "
                    f"файлом, показать «закрыто» без содержимого origin не может"))
    if normalized_card(on_ref) == normalized_card(local):
        return CloseVerdict(
            code=DELIVERED, allowed=True, ref=ref, ref_sha=sha,
            detail=f"карточка совпадает с версией на {ref} ({sha[:9]})")
    return CloseVerdict(
        code=UNDELIVERED, allowed=False, ref=ref, ref_sha=sha,
        detail=(f"карточка в этом дереве РАСХОДИТСЯ со своей версией на {ref} "
                f"({sha[:9]}): её работа есть здесь и её нет на origin"))
