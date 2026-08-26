"""Files-first card queue — parse / list / mutate Nimbalyst-native tracker cards.

stdlib-only, deterministic. Cards live as markdown with YAML-ish frontmatter in
``nimbalyst-local/tracker/*.md``. We intentionally hand-parse the small, controlled
frontmatter (no external YAML dependency — runtime is stdlib-only per repo invariant).

Card frontmatter shape (see .nimbalyst/trackers/owner-decision.yaml)::

    ---
    trackerStatus:
      type: owner-decision        # or: inbox
    title: ...
    status: needs-owner           # needs-owner | owner-accepted | owner-done | ingested
    priority: medium
    owner: someone@example.com
    ...
    ---
    <markdown body>
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from spa_core.owner_queue.status_audit import TRAIL_SEP, record_status_write, stamp_trail
from spa_core.utils.atomic import atomic_save_text

# Repo-root-relative canonical location of the files-first queue.
log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_tracker_dir() -> Path:
    """Каталог очереди владельца: ЖИВОЕ дерево, а не дерево вызывающего.

    Карточка-призрак (2026-08-22, замер на владельце): автономный цикл в
    /tmp-worktree создал owner-decision, отправил вопрос в Telegram — и умер
    вместе с worktree. Файла карточки не существовало нигде, владелец ответил
    реплаем «2», и живой бот честно сказал «не знаю такого вопроса»: вопрос,
    на который НЕЛЬЗЯ ответить по построению. Тот же worktree-vs-live класс,
    что у журнала пушей (STATE_PATH) и дедуп-реестра owner-gate.

    Порядок (зеркалит live_paths):
      1. ``SPA_TRACKER_DIR`` — явный шов (тесты, песочницы).
      2. Живое дерево (``SPA_LIVE_ROOT`` / ~/Documents/SPA_Claude) — на Маке
         карточка ложится в ПРОД-трекер и переживает worktree; бот может
         записать в неё ответ владельца.
      3. Дерево этого модуля — облако/CI, где живого дерева нет (как раньше).

    Намеренно НЕ смотрим ``SPA_DATA_DIR``: песочница гейта подменяет data/,
    но вопрос владельцу — не data, он не имеет права испаряться с песочницей.
    """
    env = os.environ.get("SPA_TRACKER_DIR")
    if env:
        return Path(env)
    from spa_core.utils.live_paths import live_root

    return live_root(_REPO_ROOT) / "nimbalyst-local" / "tracker"


TRACKER_DIR = _resolve_tracker_dir()

# Owner-only terminal status the agent must never set (CLAUDE.md invariant #14).
OWNER_ONLY_STATUS = "owner-done"

#: Владелец сказал «принято — беру в работу», а работа ещё ВПЕРЕДИ. НЕ терминальный.
#:
#: Замер #350 (население — одна карточка, и ровно она же авария): у карточки-ПОРУЧЕНИЯ
#: `owner-decision-snyat-mertvyi-adres-checkup-earn-defi-co` критерий приёмки записан в
#: ней самой («`curl -I …` больше не отвечает 404»), а нажатие «✅ Принято» 22.08 20:29Z
#: поставило `owner-done` — терминальный статус — в момент, когда критерий НЕ выполнен
#: (замер 20:47Z: всё ещё 404). Обещанной перепроверки делать стало некому: пункт выбыл
#: из очереди. Для карточки-ВЫБОРА закрытие нажатием верно и решено осознанно (ADR-075):
#: ответ И ЕСТЬ результат. Для поручения «принято» — обещание совершить действие, и
#: сводить два состояния в один терминальный статус значит терять половину из них.
#:
#: Статус ставит ТОЛЬКО владелец — по той же причине, что и `owner-done`: это его слово,
#: а не вывод агента. Агенту разрешён переход `owner-accepted → ingested`, и только
#: после того, как он сам проверил критерий приёмки и записал результат.
OWNER_ACCEPTED_STATUS = "owner-accepted"

#: Статус, который вправе поставить ТОЛЬКО владелец, и после 2026-08-26 — единственный такой.
#:
#: `owner-accepted` — это дословно СЛОВА владельца («принято, беру в работу»). Агент, ставящий
#: его, не закрывает карточку, а выдумывает чужую реплику. Разрешение 26.08 «карточки тоже
#: закрывай сам» было про ЗАКРЫТИЕ, а закрытие — это `owner-done`; `owner-accepted` нетерминален
#: (ADR-124) и закрытием не является вовсе. Поэтому он остаётся owner-only и владельцу это ничего
#: не стоит: закрывать через него было нечего.
OWNER_ONLY_STATUSES = frozenset({OWNER_ACCEPTED_STATUS})

#: Статус, закрывающий карточку. Агенту РАЗРЕШЁН с 2026-08-26 (ADR-144) — но только через
#: именованное закрытие с записанным основанием, см. `set_status(..., closed_by=, evidence=)`.
#:
#: Что здесь НЕ изменилось и почему. Запрет снят не потому, что авария #350 перестала быть
#: аварией, а потому, что он защищал не то. Замер #350: нажатие «✅ Принято» поставило
#: терминальный статус в момент, когда критерий приёмки НЕ был выполнен (карточка требовала
#: «`curl -I …` больше не отвечает 404», а спустя 18 минут он всё ещё отвечал 404) — и
#: обещанной перепроверки делать стало некому, пункт выбыл из очереди. Закрыл её ВЛАДЕЛЕЦ
#: кнопкой, не агент. Значит охраняемое свойство — не «кто нажал», а **«терминальный статус
#: означает проверенный критерий»**, и именно оно оставлено машинным: без `evidence` закрытие
#: по-прежнему ОТКАЗЫВАЕТ.
AGENT_CLOSABLE_STATUS = OWNER_ONLY_STATUS

#: Статусы, приход в которые МИМО писателя обязан звучать как CRITICAL.
#:
#: Разрешение агенту закрывать карточки (ADR-144) сняло вопрос «кому МОЖНО», но не вопрос
#: «осталась ли запись». Карточка, оказавшаяся закрытой без единого следа, подозрительна
#: одинаково независимо от того, чья рука это сделала: след — единственное, чем закрытие
#: отличается от пропажи вопроса. Поэтому сторож читает ЭТОТ набор (объединение), а не
#: `OWNER_ONLY_STATUSES`, который после ADR-144 сузился до одного имени.
#:
#: Отдельным именем, а не выражением по месту: два разъехавшихся перечня — способ замолчать
#: ровно о новом члене класса (#143–#145), и тест сверяет сторожа с этим именем.
ATTRIBUTION_CRITICAL_STATUSES = OWNER_ONLY_STATUSES | {AGENT_CLOSABLE_STATUS}

#: Статусы, с которыми карточку нельзя СОЗДАТЬ. Шире, чем owner-only, и намеренно:
#: закрытие требует ПРОВЕРЕННОГО критерия приёмки, а у новорождённой карточки проверять
#: ещё нечего. Карточка, рождённая закрытой, — это вопрос, которого никогда не задавали.
UNCREATABLE_STATUSES = ATTRIBUTION_CRITICAL_STATUSES

# Sensible default status per tracker type when a card is created without one.
# Guards against status-less "dead-letter" cards: a card with no top-level ``status:``
# line is invisible to every status filter (including the owner's needs-owner queue)
# AND unfixable by set_status. Any unknown tracker type falls back to "new".
_DEFAULT_STATUS = {"owner-decision": "needs-owner", "inbox": "new"}


class OwnerDoneForbidden(RuntimeError):
    """Raised when code attempts to set a card to ``owner-done`` (owner-only)."""


@dataclass
class Card:
    path: Path
    tracker_type: str = ""          # trackerStatus.type
    title: str = ""
    status: str = ""
    priority: str = ""
    owner: str = ""
    legacy_id: str = ""
    fields: dict = field(default_factory=dict)  # all other top-level frontmatter keys
    body: str = ""

    @property
    def id(self) -> str:
        return self.path.stem


def _split_frontmatter(text: str) -> tuple[list[str], str]:
    """Return (frontmatter_lines, body). Empty frontmatter list if none present."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return [], text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm = lines[1:i]
            body = "\n".join(lines[i + 1:])
            return fm, body
    return [], text  # unterminated frontmatter → treat as no frontmatter


def _unquote(val: str) -> str:
    """Strip matching surrounding quotes and unescape (mirrors _yaml_escape)."""
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        inner = val[1:-1]
        if val[0] == '"':
            inner = inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return val


def _parse_frontmatter(fm_lines: list[str]) -> dict:
    """Minimal parser: top-level ``key: value`` plus one nested block ``trackerStatus.type``."""
    out: dict = {}
    current_block: str | None = None
    for raw in fm_lines:
        if not raw.strip():
            continue
        indented = raw[:1].isspace()
        stripped = raw.strip()
        if ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = _unquote(val.strip())
        if not indented:
            if val == "":
                # start of a nested block (e.g. ``trackerStatus:``)
                current_block = key
                out.setdefault(key, {})
            else:
                current_block = None
                out[key] = val
        else:
            # nested line under current_block
            if current_block:
                if not isinstance(out.get(current_block), dict):
                    out[current_block] = {}
                out[current_block][key] = val
    return out


# Fallback type by filename prefix, mirroring the board builder. Last resort only:
# a card that declares nothing still has to land in ONE bucket for both readers.
_TYPE_BY_PREFIX = (
    ("owner-decision", "owner-decision"),
    ("own-", "owner-decision"),
    ("inbox-", "inbox"),
    ("agent-", "agent-task"),
)


def resolve_tracker_type(fm: dict, filename: str = "") -> str:
    """Canonical tracker-type resolution — the ONE reader both the CLI and the board use.

    Cards in the wild declare their type in two shapes and both are legitimate:
    the nested ``trackerStatus.type`` written by ``create_card`` here, and the flat
    ``type:`` written by R&D sessions by hand. ``fm`` may therefore be either the
    nested parse of this module (``{"trackerStatus": {"type": ...}}``) or the
    pre-flattened dict of ``scripts/build_tracker_board.py`` (``{"type": ...}``);
    both are accepted so the two readers cannot drift apart again.

    Why this function exists (measured, cycle #143/#144, fixed #145): the CLI read
    ONLY the nested key while the board understood both, so three ``own-rnd-*``
    cards in ``needs-owner`` — real questions to the owner, one of them about
    changing the ADR-055 tier-demotion rule — were absent from the canonical
    ``list --type owner-decision --status needs-owner`` the owner is handed in
    ``docs/STATE.md``. 20 of 23. The board said 23, the CLI said 20, and nobody
    compares two readers of the same directory. Same fail-OPEN class the project
    has paid for since #29: a reader answers ITS question ("what carries a nested
    trackerStatus.type?") and is read as answering the needed one ("what is waiting
    for the owner?"). Precedence is declaration-before-guess: nested, then flat,
    then filename.
    """
    tracker_status = fm.get("trackerStatus")
    if isinstance(tracker_status, dict):
        nested = str(tracker_status.get("type", "") or "").strip()
        if nested:
            return nested
    flat = fm.get("type")
    if isinstance(flat, str) and flat.strip():
        return flat.strip()
    name = Path(filename).name if filename else ""
    for prefix, tracker_type in _TYPE_BY_PREFIX:
        if name.startswith(prefix):
            return tracker_type
    return ""


def resolve_card_title(fm: dict, body: str = "") -> str:
    """Человеческое НАЗВАНИЕ карточки — второй общий резолвер рядом с ``resolve_tracker_type``.

    Название карточки объявляют двумя формами, и обе легитимны ровно так же, как две формы
    типа: ``title:`` во frontmatter (его пишет ``create_card``) и заголовок ``# …`` первой
    строкой тела (так пишут R&D-сессии руками, вместе с плоским ``type:``).

    Почему функция появилась (замер цикла #183 на живом трекере): из 381 карточки 9 объявляют
    себя плоской формой, и **ни у одной из них название не доезжает до владельца**. Тип для
    них починен (#145) — карточка находится в очереди, — но везде, где печатается имя, вместо
    русского предложения стоит слаг файла. На доске это выглядит так::

        - **Наша крупнейшая позиция ($40k в morpho) держится без живого подтверждения…**
        - own-rnd-xsd-rank-demotion-allocator          ← та же секция, живой вопрос владельцу

    То же в Telegram-уведомлении: заголовок сообщения «own-32-evidence-vs-curve-diverge»
    вместо «Две записи о деньгах расходятся каждый день». Это прямое нарушение инварианта
    #15 (**название карточки — по-русски**), причём название в файле ЕСТЬ — его просто никто
    не читает. Тот же класс, что и с типом: читатель честно отвечает на свой вопрос
    («что лежит в поле ``title``?»), а читают его как ответ на нужный («как называется
    карточка?»). Заодно слаг вместо названия получал и семантический дедуп
    (``history_check`` / ``ask_router`` кормят LLM именно этой строкой).

    Порядок — объявление раньше догадки: frontmatter → первый ``#``-заголовок тела → пусто
    (читатели и сегодня подставляют id/имя файла, это поведение не меняется).
    """
    declared = fm.get("title")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            return line[2:].strip()
        # Первый непустой НЕ-заголовок означает, что тело началось с текста: названия нет.
        if not line.startswith("#"):
            break
    return ""


def load_card_text(text: str, name: str = "", path: str | Path | None = None) -> Card:
    """Разобрать карточку из ТЕКСТА — тот же и единственный парсер, что и для файла на диске.

    Нужен читателям, у которых карточки нет на диске: версия карточки на ``origin/main``
    (`scripts/check_tracker_drift.py` читает её через ``git show``, а не через файл). Отдельная
    функция здесь ровно потому, что альтернатива — своя копия разбора frontmatter у второго
    читателя, а это дефект, за который проект уже заплатил дважды: CLI и доска разошлись в
    определении типа карточки и три вопроса владельца стали невидимы (#143–#145).

    ``name`` — имя файла: по нему работает последний рубеж ``resolve_tracker_type`` (префикс
    имени), когда карточка не объявила тип ни одной из двух форм.
    """
    fm_lines, body = _split_frontmatter(text)
    fm = _parse_frontmatter(fm_lines)
    tracker_type = resolve_tracker_type(fm, name)
    top = {k: v for k, v in fm.items() if k != "trackerStatus" and not isinstance(v, dict)}
    return Card(
        path=Path(path) if path is not None else Path(name),
        tracker_type=tracker_type,
        title=resolve_card_title(top, body),
        status=str(top.get("status", "")),
        priority=str(top.get("priority", "")),
        owner=str(top.get("owner", "")),
        legacy_id=str(top.get("legacy_id", "")),
        fields=top,
        body=body,
    )


def load_card(path: str | Path) -> Card:
    """Карточка с диска. Разбор — ТОЛЬКО через ``load_card_text``: две копии одного правила
    разбора и есть дефект, стоивший проекту трёх невидимых вопросов владельца (#143–#145)."""
    p = Path(path)
    return load_card_text(p.read_text(encoding="utf-8"), p.name, path=p)


def list_cards(
    tracker_type: str | None = None,
    status: str | None = None,
    tracker_dir: str | Path | None = None,
) -> list[Card]:
    """List cards, optionally filtered by trackerStatus.type and/or status."""
    d = Path(tracker_dir) if tracker_dir is not None else TRACKER_DIR
    if not d.exists():
        return []
    cards: list[Card] = []
    for p in sorted(d.glob("*.md")):
        try:
            c = load_card(p)
        except Exception:
            continue  # a malformed file must not break the whole scan (fail-open per-file)
        if tracker_type is not None and c.tracker_type != tracker_type:
            continue
        if status is not None and c.status != status:
            continue
        cards.append(c)
    return cards


def set_status(path: str | Path, new_status: str,
               closed_by: str | None = None, evidence: str | None = None) -> None:
    """Atomically rewrite the top-level ``status:`` in a card's frontmatter.

    Refuses ``owner-accepted`` outright: that status is the owner's own words, and an agent
    setting it invents a quote rather than closing anything (it is non-terminal — ADR-124).

    Accepts ``owner-done`` from an agent since 2026-08-26 (ADR-144) — the owner delegated card
    closing — **but only with `closed_by` and `evidence` given**. The property that survives is
    not "who pressed the button" (авария #350 was the owner's own press) but *a terminal status
    means the acceptance criterion was checked*. No evidence ⇒ refuse, as before.

    Only the ``status:`` line changes; the rest of the file is preserved byte-for-byte modulo
    that one line (the closure stamp is appended to the body, not the frontmatter).
    """
    if new_status in OWNER_ONLY_STATUSES:
        raise OwnerDoneForbidden(
            f"Agents may not set status '{new_status}' — that status is the owner's own words, "
            "not a verdict an agent may reach (CLAUDE.md invariant #14, ADR-144). It is "
            "non-terminal and closes nothing; to CLOSE a card use owner-done with evidence."
        )
    if new_status == AGENT_CLOSABLE_STATUS and not (closed_by and evidence):
        raise OwnerDoneForbidden(
            f"Closing a card with '{new_status}' requires closed_by= AND evidence= "
            "(CLAUDE.md invariant #14, ADR-144). A terminal status must mean the card's "
            "acceptance criterion was CHECKED — that is what авария #350 cost, and it is the "
            "half of the old guard that stays machine-enforced."
        )
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    fm_lines, _ = _split_frontmatter(text)
    if not fm_lines:
        raise ValueError(f"{p}: no frontmatter to update")

    # Статус ДО записи — половина ответа на вопрос «кто закрыл вопрос владельца»;
    # прочитать его после записи уже негде.
    _old_status = _parse_frontmatter(fm_lines).get("status")
    _old_status = str(_old_status).strip() if isinstance(_old_status, str) else None

    lines = text.splitlines(keepends=True)
    # Locate frontmatter bounds in the raw (keepends) line list.
    start = None
    end = None
    seen = 0
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            seen += 1
            if seen == 1:
                start = i
            elif seen == 2:
                end = i
                break
    if start is None or end is None:
        raise ValueError(f"{p}: could not locate frontmatter bounds")

    replaced = False
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if stripped.startswith("status:") and not lines[i][:1].isspace():
            newline = "\n" if lines[i].endswith("\n") else ""
            lines[i] = f"status: {new_status}{newline}"
            replaced = True
            break
    if not replaced:
        # Repair a status-less card (dead-letter): insert a top-level 'status:' line as
        # the last frontmatter entry, right before the closing '---'. Without this, a card
        # created with no status is invisible to every filter AND unfixable by this tool.
        lines.insert(end, f"status: {new_status}\n")

    # След перехода едет В САМОЙ карточке — решение владельца 2026-08-23, вариант 1
    # (ADR-129). Одной записью со статусом, а не двумя: журнал в `data/` в git не
    # попадает, поэтому законное закрытие из рабочего дерева приезжало в прод немым,
    # и сторож называл его «вопрос владельца закрыли без владельца» КАЖДЫЙ раз.
    #
    # Закрытие агентом (ADR-144) едет ТЕМ ЖЕ следом, а не своей параллельной записью: кто
    # закрыл и на каком основании — половина ответа на «почему карточка закрыта», и она
    # обязана лежать там же, где остальные переходы, иначе появится второй источник правды.
    # Разделитель следа из основания вычищается: иначе основание с ` · ` внутри развалило бы
    # разбор строки на поля.
    _source = "queue.set_status"
    if new_status == AGENT_CLOSABLE_STATUS and closed_by and evidence:
        _clean = str(evidence).replace(TRAIL_SEP.strip(), "-").replace("\n", " ").strip()
        _source = f"queue.set_status/closed_by:{closed_by}/evidence:{_clean[:200]}"
    _text = stamp_trail("".join(lines), old=_old_status, new=new_status,
                        source=_source)
    atomic_save_text(_text, str(p))
    # Кто перевёл карточку — в журнал. Импорт наверху, а не здесь: аудит держится
    # на одной stdlib и кольца не создаёт, а «на всякий случай локальный» импорт —
    # это молчаливая своя копия правила, за которую проект уже платил (#144).
    record_status_write(p, old=_old_status, new=new_status, source="queue.set_status")


def first_instruction_line(card: Card) -> str:
    """First meaningful instruction line for a Telegram notification.

    Prefers the first non-empty line under an '## Инструкция' / '## Instruction' heading;
    falls back to the first non-empty body line; then to the title.
    """
    body_lines = card.body.splitlines()
    in_instr = False
    for ln in body_lines:
        low = ln.strip().lower()
        if ln.strip().startswith("##"):
            in_instr = (
                low.startswith("## что от тебя нужно")   # §2.4 (amended format)
                or low.startswith("## инструкц")          # legacy format
                or low.startswith("## instruction")
                or low.startswith("## what")
            )
            continue
        if in_instr and ln.strip():
            return ln.strip().lstrip("0123456789.-) ").strip() or ln.strip()
    for ln in body_lines:
        if ln.strip() and not ln.strip().startswith("#"):
            return ln.strip()
    return card.title


def iter_cards(cards: Iterable[Card]) -> Iterable[Card]:
    return cards


# Cyrillic → Latin transliteration so Russian card titles produce READABLE filenames
# (e.g. "Добавить кнопку наверх" → "dobavit-knopku-naverh") instead of collapsing to the
# opaque fallback "note". This is for internal card filenames ONLY — NOT site copy, where
# transliteration is forbidden (.claude/rules/site-copy.md, memory ru-copy-quality-no-translit).
_CYR_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def _translit(text: str) -> str:
    """Best-effort Cyrillic→Latin for readable ASCII slugs. Non-Cyrillic passes through."""
    return "".join(_CYR_TRANSLIT.get(ch, ch) for ch in text)


def _slug(text: str, maxlen: int = 40) -> str:
    """Readable ASCII slug for a filename; transliterates Cyrillic first so Russian
    titles stay human-readable. Falls back to 'note' only if truly nothing survives."""
    s = re.sub(r"[^a-z0-9]+", "-", _translit((text or "").lower())).strip("-")
    return (s[:maxlen].strip("-")) or "note"


def _yaml_escape(value: str) -> str:
    """Quote a scalar for the frontmatter if it contains YAML-significant chars."""
    v = str(value)
    if v == "" or re.search(r"""[:#\[\]{}&*!|>'"%@`]|^\s|\s$""", v):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


#: Статусы, в которых вопрос ВСЁ ЕЩЁ ждёт ответа. Закрытая карточка идемпотентность не
#: даёт: если вопрос вернулся после закрытия — это новый вопрос, и о нём надо сказать.
#: `owner-accepted` тоже открыт: владелец согласился, а СДЕЛАНО ещё ничего не было
#: (#350). Считать его закрытым значило бы вернуть ровно ту потерю, ради которой
#: статус и заведён.
_OPEN_STATUSES = frozenset({"needs-owner", "new", "in-progress", "blocked",
                            OWNER_ACCEPTED_STATUS})


def _open_twin(d: Path, base: str, tracker_type: str, body: str) -> Path | None:
    """Уже открытая карточка с ТЕМ ЖЕ вопросом, если она есть.

    Тип карточки отдельно НЕ сверяется: он входит в ``base`` (``inbox-…`` против
    ``owner-decision-…``), поэтому карточки разных типов физически не могут совпасть
    именем. Лишняя проверка выглядела бы защитой, которой нечего защищать.

    Никогда не бросает: сбой поиска не имеет права ПОДАВИТЬ карточку — в сомнении
    возвращаем ``None`` и карточка создаётся. Лишняя карточка — неприятность, потерянный
    вопрос владельцу — потеря контроля.
    """
    try:
        wanted = (body or "").strip()
        candidates = [d / f"{base}.md"] + sorted(d.glob(f"{base}-[0-9]*.md"))
        for cand in candidates:
            if not cand.exists():
                continue
            try:
                card = load_card(cand)
            except Exception:  # noqa: BLE001 — битую карточку близнецом не считаем
                continue
            if (card.status or "") not in _OPEN_STATUSES:
                continue
            if (card.body or "").strip() == wanted:
                return cand
    except Exception:  # noqa: BLE001
        return None
    return None


def create_card(
    tracker_type: str,
    title: str,
    body: str = "",
    *,
    status: str | None = None,
    source: str | None = None,
    extra_fields: dict | None = None,
    tracker_dir: str | Path | None = None,
    now: datetime | None = None,
) -> Path:
    """Create a new tracker card as a `trackerStatus`-frontmatter markdown file.

    Deterministic given ``now`` (pass one in tests). Filename is built from a HUMAN
    slug of the title — ``<tracker_type>-<slug>.md`` (e.g. ``inbox-dobavit-knopku.md``) —
    so cards are readable; the UTC timestamp is no longer in the name (it lived only to
    disambiguate, and made IDs opaque — owner feedback inbox-task-readable-card-ids). A
    short numeric suffix is appended ONLY on collision (``-2``, ``-3`` …). The date is
    still recorded in the ``created:`` frontmatter field.
    Never sets ``owner-done`` / ``owner-accepted`` — callers create in an open state.
    This stays true after ADR-144 let agents CLOSE cards: closing demands a checked
    acceptance criterion, and a newborn card has nothing checked yet. A card born closed
    is a question that was never actually asked.
    """
    if status in UNCREATABLE_STATUSES:
        raise OwnerDoneForbidden(
            f"create_card must not set '{status}': a card is never born closed "
            "(invariant #14, ADR-144). Create it open, then close it with evidence.")
    d = Path(tracker_dir) if tracker_dir is not None else TRACKER_DIR
    d.mkdir(parents=True, exist_ok=True)
    dt = now or datetime.now(timezone.utc)
    date_str = dt.strftime("%Y-%m-%d")

    base = f"{tracker_type}-{_slug(title)}"
    path = d / f"{base}.md"

    # ИДЕМПОТЕНТНОСТЬ. Тот же вопрос, заданный второй раз, — это НЕ вторая карточка.
    #
    # Замер 08–09.08: автоматические авторы (owner-gate сайта и другие) при каждом повторе
    # своей проверки заводили НОВУЮ карточку `-2`, `-3`… и КАЖДАЯ слала владельцу отдельное
    # уведомление. Владелец получал одно и то же «нужно решение» каждые несколько минут —
    # «с этим невозможно работать». Чинить это у каждого автора по очереди бессмысленно:
    # авторов много, и завтра появится новый. Поэтому защита стоит здесь — в ЕДИНСТВЕННОЙ
    # точке, через которую карточки рождаются.
    #
    # Условие узкое и проверяемое: тот же заголовок (⇒ то же имя файла), то же тело И
    # карточка всё ещё ОТКРЫТА. Изменилось тело — вопрос другой, заводим новую с суффиксом.
    # Карточка закрыта — вопрос вернулся, тоже новая.
    existing = _open_twin(d, base, tracker_type, body)
    if existing is not None:
        log.info("create_card: открытая карточка с тем же вопросом уже есть (%s) — "
                 "не плодим дубль", existing.name)
        return existing

    n = 2
    while path.exists():  # collision guard → readable numeric suffix (-2, -3, …)
        path = d / f"{base}-{n}.md"
        n += 1

    # Always emit a status line (never a dead-letter card): fall back to the tracker's
    # default when the caller passes none.
    effective_status = status or _DEFAULT_STATUS.get(tracker_type, "new")
    lines = ["---", "trackerStatus:", f"  type: {tracker_type}", f"title: {_yaml_escape(title)}"]
    lines.append(f"status: {effective_status}")
    if source:
        lines.append(f"source: {source}")
    lines.append(f"created: {date_str}")
    for k, v in (extra_fields or {}).items():
        lines.append(f"{k}: {_yaml_escape(str(v))}")
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip("\n") if body else "")
    lines.append("")

    atomic_save_text("\n".join(lines), str(path))
    return path


# Repo-root inbox/ folder for loose Obsidian notes (Этап 6, path 2).
INBOX_NOTES_DIR = Path(os.environ.get("SPA_INBOX_NOTES_DIR", _REPO_ROOT / "inbox"))

# Knowledge-base dirs scanned for the owner's `#promote` tag (Этап 7.3).
PROMOTE_DIRS = (_REPO_ROOT / "docs" / "ideas", _REPO_ROOT / "docs" / "rules-draft")
# `#promote` as a whole tag, but NOT the already-processed `#promoted...`.
_PROMOTE_RE = re.compile(r"(?<![\w#])#promote(?![\w-])", re.IGNORECASE)


@dataclass
class Promotion:
    path: Path
    title: str
    snippet: str


def scan_promotions(dirs: Iterable[str | Path] | None = None) -> list[Promotion]:
    """Find notes tagged ``#promote`` in docs/ideas/ and docs/rules-draft/.

    Returns items the orchestrator must convert into a rule (.claude/rules / CLAUDE.md),
    an ADR (docs/decisions/), or a task card — then mark the source ``#promoted``
    (per docs/ORCHESTRATOR_PROTOCOL.md §Promotion). ``#promoted`` is NOT matched.
    """
    scan = [Path(d) for d in dirs] if dirs is not None else list(PROMOTE_DIRS)
    out: list[Promotion] = []
    for d in scan:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*.md")):
            if p.name.lower() == "readme.md":
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            if not _PROMOTE_RE.search(text):
                continue
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            title = next((ln.lstrip("# ").strip() for ln in lines), p.stem)
            snippet = next((ln for ln in lines if _PROMOTE_RE.search(ln)), title)
            out.append(Promotion(path=p, title=title, snippet=snippet[:200]))
    return out


def ingest_notes(
    notes_dir: str | Path | None = None,
    tracker_dir: str | Path | None = None,
    now: datetime | None = None,
) -> list[Path]:
    """Convert loose Obsidian notes in ``notes_dir`` into Inbox cards.

    Each ``*.md`` / ``*.txt`` note (excluding README and the archive) becomes an
    ``inbox`` card (source=obsidian), then the original is moved to
    ``<notes_dir>/.ingested/`` so it is not processed twice. Returns created card paths.
    """
    d = Path(notes_dir) if notes_dir is not None else INBOX_NOTES_DIR
    if not d.exists():
        return []
    archive = d / ".ingested"
    created: list[Path] = []
    for p in sorted(list(d.glob("*.md")) + list(d.glob("*.txt"))):
        if p.name.lower() in ("readme.md", "readme.txt"):
            continue
        try:
            content = p.read_text(encoding="utf-8").strip()
            if not content:
                continue
            # If the note already has trackerStatus frontmatter, skip (it's a card, not a note).
            if content.startswith("---") and "trackerStatus" in content[:200]:
                continue
            title = next((ln.strip().lstrip("# ").strip() for ln in content.splitlines() if ln.strip()), p.stem)
            body = "\n".join([
                "## Задание (заметка Obsidian)", "", content, "",
                "---",
                "_Оркестратор: классифицируй (задача/идея/непонятно), закрой карточку со ссылкой на "
                "порождённую работу (§6.4)._",
            ])
            card = create_card("inbox", title, body, status="new", source="obsidian",
                               tracker_dir=tracker_dir, now=now)
            created.append(card)
            archive.mkdir(parents=True, exist_ok=True)
            p.replace(archive / p.name)
        except Exception:
            continue  # one bad note must not block the rest (fail-open per-file)
    return created
