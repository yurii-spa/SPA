#!/usr/bin/env python3
"""Линтер инструкции владельцу — то, что мы просим открыть, обязано существовать.

Авария, из которой родился модуль (22.08.2026)
------------------------------------------------------------------------------
Владельцу ушёл вопрос: «открой ``/api/pilot/requests/count`` и посмотри поле
``notify_channel``». **Такого поля в коде не было НИ РАЗУ** — ``grep notify_channel``
по всему репозиторию находил только текст самой карточки. Владелец нажал «вариант 1 —
там ``configured: true``». Ответ пришёл, карточка закрылась, решение записано — а
прочитать было НЕЧЕГО.

Это не описка, это класс: **инструкция владельцу — тоже утверждение о системе, и его
никто не проверяет.** Ответ на несуществующее поле неотличим от настоящего замера: и то
и другое приходит как ``owner_choice: 1``. Цикл #346 закрыл конкретный случай (поле
добавлено и меряется сторожем ``lead_channel_watch``, ADR-121) — но следующая карточка
снова могла послать владельца читать выдуманный путь, кнопку или страницу.

Что проверяется и на каком праве
------------------------------------------------------------------------------
Читается РОВНО одна секция карточки — ``## Что от тебя нужно`` (формат §2.4, инвариант
#15). Это единственное место, которое адресовано владельцу как поручение; «что
случилось» и «что будет после» — рассказ о системе, там ссылка на будущий артефакт
законна.

Из секции извлекаются четыре вида ссылок, каждый со своим способом разрешения:

===============  ==========================================================
``api_path``     ``/api/...`` — ищется ЛИТЕРАЛОМ в коде (роуты объявлены
                 полным путём: ``@router.get("/api/pilot/requests/count")``,
                 ни один ``APIRouter`` в проекте не имеет ``prefix=``).
                 Путь внутри АДРЕСА достаётся разбором URL, а не поиском по
                 нему: в ``https://api.earn-defi.com:8765/api/pilot/requests/count``
                 перед ``/api/`` стоит цифра порта, и regex с ``(?<![\\w.])``
                 её не пропускал — ровно карточка 22.08 уходила ``unchecked``
                 (замер #365)
``repo_path``    ``spa_core/...``, ``docs/...`` — проверяется файловой системой
``field``        одиночный идентификатор в обратных кавычках
                 (``notify_channel``, ``TELEGRAM_CHAT_ID_SPA``) — ищется в
                 коде как токен
``module``       ``spa_core.monitoring.foo`` — проверяется файлом/пакетом
``site_url``     внешняя страница — **не измеряется** (сеть в проверке
                 запрещена: инвариант «только stdlib», тесты офлайн)
===============  ==========================================================

**Правом запрещать обладает только ДОКАЗАННОЕ отсутствие.** Всё, что не удалось
разобрать или измерить, — ``unchecked``: оно НАЗЫВАЕТСЯ в отчёте и не мешает работе
(требование п.3 карточки). Иначе линтер, споткнувшись о формулировку, замолчал бы
владельцу целую очередь вопросов — это дороже той аварии, которую он лечит.

**Карточка не может быть сама себе доказательством.** Индекс кода собирается по
``spa_core/``, ``scripts/``, ``landing/src/``, ``launchd/``, ``.github/`` и НЕ включает
``nimbalyst-local/`` и ``docs/``: 22.08 единственным вхождением ``notify_channel`` был
текст самой карточки, и корпус, включающий трекер, назвал бы аварию нормой.

**И ЭТОТ ФАЙЛ — тоже не доказательство (замер цикла #365).** Исключить трекер оказалось
мало: как только линтер ОПИСАЛ аварию, его собственный докстринг внёс ``notify_channel``
(4 вхождения) и ``/api/pilot/requests/count`` в тот самый корпус, по которому судит.
Откати`те` ADR-121 — поле исчезнет из системы, но останется в нашем рассказе о нём, и
сторож ответил бы ``ok`` о том, чего нет. Проверка, доказывающая себя своим же текстом,
не проверка. Поэтому у ``.py`` РАЗДЕЛЯЮТСЯ **код** и **проза** (комментарии и докстринги):

* токен есть в коде — ``ok`` (настоящее вхождение ``"notify_channel"`` живёт строкой-литералом
  в ``spa_core/api/routers/interest.py``, а строковые литералы — это система, их НЕ снимаем);
* токен есть ТОЛЬКО в прозе — ``unchecked`` с названной причиной, а НЕ ``ok`` и НЕ ``missing``:
  описание — не наличие, но и не доказанное отсутствие;
* нигде — ``missing``, и только это даёт право запрещать (22.08: ни кода, ни прозы).

Файлы не-``.py`` разбору на код/прозу не подвергаются (там нет дешёвого надёжного
разделителя) — их вклад целиком считается кодом. Это названное ограничение, а не недосмотр.

Где включён
------------------------------------------------------------------------------
:func:`spa_core.owner_queue.first_delivery.deliver_new_questions` — ПЕРВАЯ доставка
вопроса. Заблокированная карточка не тратит потолок прогона и названа поимённо в отчёте
и в строке для человека. Повторы/пересылки (``resend``) намеренно не трогаются: там
владелец уже видел текст, и запрет уже доставленного ничего не лечит.

Только stdlib, без сети. LLM здесь запрещён — это разрешение имён, а не суждение.
"""

from __future__ import annotations

import io
import json
import logging
import re
import tokenize
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

log = logging.getLogger(__name__)

#: Секция карточки, адресованная владельцу (формат §2.4). Только её и читаем.
INSTRUCTION_HEADING = "что от тебя нужно"

OK = "ok"
MISSING = "missing"
UNCHECKED = "unchecked"

#: Причина для токена, который встречается ТОЛЬКО в комментариях/докстрингах.
#: Это НЕ наличие (рассказ о поле — не поле) и НЕ доказанное отсутствие ⇒ не запрет.
PROSE_ONLY_REASON = ("встречается только в комментарии/докстринге — это описание системы, "
                     "а не сама система; наличия не доказывает, отсутствия тоже")

#: Где живёт «система». Трекер и docs сюда НЕ входят намеренно — см. докстринг.
CODE_DIRS: Tuple[str, ...] = ("spa_core", "scripts", "landing/src", "launchd", ".github")
CODE_SUFFIXES = frozenset({
    ".py", ".sh", ".bash", ".ts", ".tsx", ".js", ".mjs", ".astro", ".json", ".jsonl",
    ".yml", ".yaml", ".plist", ".html", ".css", ".sql", ".toml", ".ini", ".cfg",
})
SKIP_DIRS = frozenset({"__pycache__", "node_modules", ".git", "dist", ".astro", ".venv"})

#: Рантайм-домен: состояние, которое ПИШЕТСЯ на ходу и в .gitignore. В свежем рабочем
#: дереве его нет ПО ПОСТРОЕНИЮ, поэтому «файла нет» здесь — свойство дерева, а не
#: системы. Замер #365: из 12 «несуществующих» файлов 5 живут в проде прямо сейчас
#: (``data/intraday_equity.json``, ``data/derisk_status.json``, ``data/telegram/push_state.json``,
#: ``data/worktree_reap_log.jsonl``, ``data/tracker_status_snapshot.json``) — линтер,
#: запущенный из worktree, ЗАПРЕТИЛ БЫ пять настоящих вопросов владельцу. Молчащая
#: очередь дороже той аварии, которую мы лечим (п.3 карточки), поэтому здесь только
#: «не измерено», и никогда — запрет.
RUNTIME_DIRS: Tuple[str, ...] = ("data/",)

#: Каталоги репозитория, ссылку на которые разрешает файловая система.
REPO_DIRS: Tuple[str, ...] = (
    "spa_core", "scripts", "docs", "data", "landing", "nimbalyst-local", "launchd",
    "tests", "inbox", ".claude", ".github",
)

_URL_RE = re.compile(r"https?://[^\s`)\]>,;\"']+")
#: Схема + хост(+порт) адреса — всё до первого ``/`` пути.
_URL_HOST_RE = re.compile(r"^https?://[^/]*")
_API_RE = re.compile(r"(?<![\w.])/api/[A-Za-z0-9_\-/{}]*[A-Za-z0-9_}]")
_PATH_RE = re.compile(
    r"(?<![\w/.\-])(?:" + "|".join(re.escape(d) for d in REPO_DIRS) +
    r")/[A-Za-z0-9_\-./]*[A-Za-z0-9_\-]"
)
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DOTTED_RE = re.compile(r"^(?:spa_core|scripts)(?:\.[A-Za-z0-9_]+)+$")

_IDX_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_IDX_PATH_RE = re.compile(r"/[A-Za-z0-9_\-./{}]{2,}")

#: Индекс кода на корень дерева. Собирается один раз за процесс: 4116 файлов / ~69 МБ.
_INDEX_CACHE: Dict[str, "CodeIndex"] = {}


def repo_root() -> Path:
    """Корень репозитория, посчитанный от файла модуля (не от ``cwd``).

    ``cwd`` здесь врал бы: доставка ходит из любого рабочего дерева, а вопрос «есть ли
    поле в системе» относится к тому дереву, из которого исполняется код.
    """
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CodeIndex:
    """Что есть в коде — и ОТДЕЛЬНО то, что есть лишь в рассказе о коде.

    Разделение появилось замером #365: докстринг самого линтера внёс в корпус токены
    аварии, которую он описывает, и сторож начал доказывать себя собственным текстом.
    """

    identifiers: Set[str]
    paths: Set[str]
    files_scanned: int
    #: Токены/пути, встреченные ТОЛЬКО в комментариях и докстрингах ``.py``.
    prose_identifiers: Set[str] = field(default_factory=set)
    prose_paths: Set[str] = field(default_factory=set)

    def has_identifier(self, token: str) -> bool:
        return token in self.identifiers

    def has_path(self, token: str) -> bool:
        return token in self.paths

    def prose_only_identifier(self, token: str) -> bool:
        return token not in self.identifiers and token in self.prose_identifiers

    def prose_only_path(self, token: str) -> bool:
        return token not in self.paths and token in self.prose_paths


def split_code_and_prose(text: str) -> Tuple[str, str]:
    """Разделить python-исходник на код и прозу (комментарии + докстринги).

    Делит РОВНО по токенам, а не подстрокам: ``ast.get_docstring`` отдаёт РАЗОБРАННОЕ
    значение (``\\w`` в исходнике приходит как ``\\\\w``), вырезание такого «докстринга»
    из исходника молча не находит ничего — и докстринг остаётся в коде. Именно так первая
    версия этой правки прошла мимо: линтер продолжал доказывать себя своим текстом, а тест
    на самопитание был бы зелёным украшением. ``tokenize`` отдаёт ИСХОДНЫЙ текст токена.

    **Строковые литералы НЕ проза** и остаются в коде: настоящее вхождение
    ``notify_channel`` — это ключ словаря ``"notify_channel": _notify_channel_status()``
    в ``interest.py``. Снять литералы значило бы стереть ровно то доказательство, ради
    которого проверка существует, и получить ложное «поля нет» — запрет на пустом месте.
    Докстринг от литерала отличается позицией: он — самостоятельный оператор, то есть
    первый значимый токен логической строки.

    Не разобрали (синтаксическая ошибка, экзотическая кодировка) ⇒ ВЕСЬ текст считается
    кодом. Проверка не имеет права выдумывать отсутствие из-за того, что сама споткнулась.
    """
    #: После этих токенов STRING стоит в начале оператора ⇒ это докстринг, а не литерал.
    openers = frozenset({tokenize.NEWLINE, tokenize.NL, tokenize.INDENT,
                         tokenize.DEDENT, tokenize.ENCODING})
    code_parts: List[str] = []
    prose_parts: List[str] = []
    prev_significant = tokenize.ENCODING  # начало файла — тоже позиция докстринга
    depth = 0  # глубина скобок: внутри них «начала оператора» не бывает
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                prose_parts.append(tok.string)
                continue  # комментарий не меняет «начало оператора»
            # ГЛУБИНА ОБЯЗАТЕЛЬНА. Внутри скобок перевод строки приходит как NL, и без
            # счётчика ключ многострочного словаря читался бы докстрингом — а это ровно
            # форма настоящего доказательства: `return {\n    "notify_channel": ...}`
            # в `interest.py`. Замер #365 поймал это на второй версии починки: проверка
            # молча теряла бы литералы по всему корпусу.
            if tok.type == tokenize.OP:
                if tok.string in "([{":
                    depth += 1
                elif tok.string in ")]}":
                    depth = max(0, depth - 1)
            if (tok.type == tokenize.STRING and depth == 0
                    and prev_significant in openers):
                prose_parts.append(tok.string)
            else:
                code_parts.append(tok.string)
            prev_significant = tok.type
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return text, ""
    if not prose_parts:
        return text, ""
    return "\n".join(code_parts), "\n".join(prose_parts)


def build_index(root: Optional[Path] = None, *, dirs: Sequence[str] = CODE_DIRS) -> CodeIndex:
    """Собрать индекс кода. Нечитаемый файл пропускается молча — он не доказательство."""
    base = Path(root) if root is not None else repo_root()
    idents: Set[str] = set()
    paths: Set[str] = set()
    prose_idents: Set[str] = set()
    prose_paths: Set[str] = set()
    scanned = 0
    for rel in dirs:
        top = base / rel
        if not top.is_dir():
            continue
        for path in top.rglob("*"):
            if not path.is_file() or path.suffix not in CODE_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            # У ``.py`` рассказ о системе отделяется от системы (#365). Остальные
            # суффиксы идут целиком в код — названное ограничение, см. докстринг модуля.
            if path.suffix == ".py":
                code_text, prose_text = split_code_and_prose(text)
            else:
                code_text, prose_text = text, ""
            idents.update(_IDX_IDENT_RE.findall(code_text))
            paths.update(_IDX_PATH_RE.findall(code_text))
            if prose_text:
                prose_idents.update(_IDX_IDENT_RE.findall(prose_text))
                prose_paths.update(_IDX_PATH_RE.findall(prose_text))
    return CodeIndex(identifiers=idents, paths=paths, files_scanned=scanned,
                     prose_identifiers=prose_idents, prose_paths=prose_paths)


def index_for(root: Optional[Path] = None) -> CodeIndex:
    """Индекс с кэшем на процесс. Ключ — РАЗРЕШЁННЫЙ путь корня."""
    base = (Path(root) if root is not None else repo_root()).resolve()
    key = str(base)
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = build_index(base)
    return _INDEX_CACHE[key]


@dataclass
class Reference:
    """Одна ссылка из инструкции владельцу и её судьба."""

    kind: str
    token: str
    status: str
    reason: str = ""


@dataclass
class LintResult:
    card_id: str
    #: Нашлась ли секция «Что от тебя нужно». False ⇒ мерить было нечего.
    section_found: bool = False
    refs: List[Reference] = field(default_factory=list)
    #: Причина, по которой измерение вообще не состоялось (не запрет).
    unmeasured_reason: str = ""

    @property
    def missing(self) -> List[Reference]:
        return [r for r in self.refs if r.status == MISSING]

    @property
    def unchecked(self) -> List[Reference]:
        return [r for r in self.refs if r.status == UNCHECKED]

    @property
    def blocked(self) -> bool:
        """Запрещаем ТОЛЬКО доказанное отсутствие — ничего другого."""
        return bool(self.missing)

    def reason_line(self) -> str:
        """Причина словами: что именно велели открыть и чего в системе нет."""
        if not self.missing:
            return ""
        parts = [f"{r.token} ({_KIND_RU.get(r.kind, r.kind)})" for r in self.missing]
        return ("инструкция владельцу ссылается на то, чего в системе нет: "
                + ", ".join(parts))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["blocked"] = self.blocked
        d["reason"] = self.reason_line()
        return d


_KIND_RU = {
    "api_path": "путь API",
    "repo_path": "файл репозитория",
    "field": "поле/идентификатор",
    "module": "python-модуль",
    "site_url": "внешняя страница",
}


def instruction_section(text: str) -> Optional[str]:
    """Текст секции «Что от тебя нужно» — до следующего заголовка ``##``.

    Ищем по нормализованному заголовку: в живых карточках встречаются эмодзи и лишние
    пробелы, а падать из-за оформления линтер не имеет права.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if not line.startswith("##"):
            continue
        head = line.lstrip("#").strip().lower()
        head = re.sub(r"[^а-яёa-z ]+", "", head).strip()
        if head.startswith(INSTRUCTION_HEADING):
            start = i + 1
            break
    if start is None:
        return None
    out: List[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out)


def extract_references(section: str) -> List[Reference]:
    """Разобрать секцию на ссылки. Порядок стабилен, дубли сняты по (вид, токен)."""
    found: List[Reference] = []
    seen: Set[Tuple[str, str]] = set()

    def add(kind: str, token: str, status: str = "", reason: str = "") -> None:
        key = (kind, token)
        if key in seen:
            return
        seen.add(key)
        found.append(Reference(kind=kind, token=token, status=status or "", reason=reason))

    # 1. URL. Путь API внутри адреса — это ссылка на НАШ роут (ровно случай 22.08:
    #    владельцу дали `https://api.earn-defi.com:8765/api/pilot/requests/count`).
    for url in _URL_RE.findall(section):
        # Путь берётся ОТБРАСЫВАНИЕМ хоста, а не поиском ``_API_RE`` по всему адресу:
        # в `https://api.earn-defi.com:8765/api/pilot/requests/count` перед `/api/` стоит
        # цифра порта, а lookbehind `(?<![\w.])` цифру не пропускает — и ровно карточка
        # 22.08 (та самая авария) уезжала «не измерено» вместо проверки (замер #365).
        path_part = _URL_HOST_RE.sub("", url)
        m = _API_RE.search(path_part) if path_part.startswith("/") else _API_RE.search(url)
        if m:
            add("api_path", m.group(0))
        else:
            add("site_url", url, UNCHECKED,
                "внешняя страница: сеть в проверке запрещена (только stdlib, офлайн)")

    # 2. Пути API вне адресов.
    for token in _API_RE.findall(section):
        add("api_path", token)

    # 3. Пути репозитория.
    for token in _PATH_RE.findall(section):
        add("repo_path", token)

    # 4. Одиночные токены в обратных кавычках: поля, переменные окружения, модули.
    for raw in _BACKTICK_RE.findall(section):
        token = raw.strip().strip(".,;:()")
        if not token or " " in token:
            continue
        if _DOTTED_RE.match(token):
            add("module", token)
            continue
        if not _IDENT_RE.match(token):
            continue
        if len(token) < 4:
            continue
        # `_` или ВЕРХНИЙ_РЕГИСТР — признак имени в системе, а не обычного слова.
        if "_" not in token and not token.isupper():
            continue
        if token in REPO_DIRS:
            continue
        add("field", token)
    return found


def resolve(refs: Sequence[Reference], *, root: Optional[Path] = None,
            index: Optional[CodeIndex] = None) -> List[Reference]:
    """Проставить каждой ссылке статус. Индекс строится ЛЕНИВО — только если нужен."""
    base = (Path(root) if root is not None else repo_root()).resolve()
    out: List[Reference] = []
    idx = index

    def code() -> CodeIndex:
        nonlocal idx
        if idx is None:
            idx = index_for(base)
        return idx

    for ref in refs:
        if ref.status:  # уже решено при извлечении (site_url)
            out.append(ref)
            continue
        kind, token = ref.kind, ref.token
        if kind == "api_path":
            if code().has_path(token):
                out.append(Reference(kind, token, OK))
            elif code().prose_only_path(token):
                out.append(Reference(kind, token, UNCHECKED, PROSE_ONLY_REASON))
            else:
                out.append(Reference(kind, token, MISSING,
                                     "такого пути нет ни одним литералом в коде"))
        elif kind == "repo_path":
            if any(ch in token for ch in "*<>{}"):
                out.append(Reference(kind, token, UNCHECKED, "путь с подстановкой"))
            elif (base / token).exists():
                out.append(Reference(kind, token, OK))
            elif token.startswith(RUNTIME_DIRS):
                out.append(Reference(
                    kind, token, UNCHECKED,
                    "рантайм-состояние: в этом дереве не материализовано (.gitignore), "
                    "отсутствия в системе НЕ доказывает"))
            else:
                out.append(Reference(kind, token, MISSING, "файла/каталога нет в дереве"))
        elif kind == "module":
            rel = Path(token.replace(".", "/"))
            if (base / rel).is_dir() or (base / rel.with_suffix(".py")).is_file():
                out.append(Reference(kind, token, OK))
            else:
                out.append(Reference(kind, token, MISSING, "модуля нет в дереве"))
        elif kind == "field":
            if code().has_identifier(token):
                out.append(Reference(kind, token, OK))
            elif code().prose_only_identifier(token):
                out.append(Reference(kind, token, UNCHECKED, PROSE_ONLY_REASON))
            else:
                out.append(Reference(kind, token, MISSING,
                                     "имя не встречается в коде ни разу"))
        else:  # незнакомый вид — не измерено, а не запрет
            out.append(Reference(kind, token, UNCHECKED, "вид ссылки не разбирается"))
    return out


def lint_text(text: str, *, card_id: str = "", root: Optional[Path] = None,
              index: Optional[CodeIndex] = None) -> LintResult:
    """Проверить текст карточки. Не бросает: не разобрали ⇒ «не измерено»."""
    try:
        section = instruction_section(text)
    except Exception as exc:  # noqa: BLE001 — оформление не даёт права молчать владельцу
        return LintResult(card_id, False, [], f"секцию не разобрать: {exc!r}")
    if section is None:
        return LintResult(card_id, False, [],
                          "секции «Что от тебя нужно» нет — мерить нечего")
    try:
        refs = resolve(extract_references(section), root=root, index=index)
    except Exception as exc:  # noqa: BLE001
        return LintResult(card_id, True, [], f"ссылки не разрешены: {exc!r}")
    return LintResult(card_id, True, refs)


def lint_card(path: str | Path, *, root: Optional[Path] = None,
              index: Optional[CodeIndex] = None) -> LintResult:
    """То же по файлу карточки. Нечитаемый файл — «не измерено», не запрет."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return LintResult(p.stem, False, [], f"карточка не читается: {exc!r}")
    return lint_text(text, card_id=p.stem, root=root, index=index)


# ─────────────────────────── замер масштаба (п.1 карточки) ───────────────────────────

def audit(tracker_dir: str | Path, *, root: Optional[Path] = None) -> dict:
    """Пройти по всем карточкам трекера и посчитать, сколько ссылок РАЗРЕШАЕТСЯ.

    Замер — не украшение: без числа «сколько инструкций владельцу сегодня неисполнимы»
    починка остаётся утверждением.
    """
    base = (Path(root) if root is not None else repo_root()).resolve()
    idx = index_for(base)
    cards = sorted(Path(tracker_dir).glob("*.md"))
    by_kind: Dict[str, Dict[str, int]] = {}
    blocked: List[dict] = []
    with_section = 0
    refs_total = 0
    for card in cards:
        if card.name.startswith("_"):  # _BOARD.md — авто-индекс, не карточка
            continue
        res = lint_card(card, root=base, index=idx)
        if res.section_found:
            with_section += 1
        for ref in res.refs:
            refs_total += 1
            slot = by_kind.setdefault(ref.kind, {OK: 0, MISSING: 0, UNCHECKED: 0})
            slot[ref.status] = slot.get(ref.status, 0) + 1
        if res.blocked:
            blocked.append({"card": card.stem, "reason": res.reason_line(),
                            "missing": [r.token for r in res.missing]})
    totals = {OK: 0, MISSING: 0, UNCHECKED: 0}
    for slot in by_kind.values():
        for k, v in slot.items():
            totals[k] = totals.get(k, 0) + v
    return {"tracker_dir": str(tracker_dir), "cards": len(cards),
            "cards_with_instruction_section": with_section,
            "files_indexed": idx.files_scanned, "refs": refs_total,
            "totals": totals, "by_kind": by_kind,
            "blocked_cards": blocked}


def _main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--card", help="проверить одну карточку (путь)")
    ap.add_argument("--audit", action="store_true", help="замер по всему трекеру")
    ap.add_argument("--tracker-dir", default=None,
                    help="каталог карточек (по умолчанию nimbalyst-local/tracker)")
    ap.add_argument("--json", action="store_true", help="вывод машиной")
    args = ap.parse_args(argv)

    root = repo_root()
    if args.card:
        res = lint_card(args.card, root=root)
        if args.json:
            print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"{res.card_id}: " + ("❌ " + res.reason_line() if res.blocked
                                        else "✅ инструкция разрешается"))
            for ref in res.refs:
                print(f"   [{ref.status}] {ref.kind} {ref.token}"
                      + (f" — {ref.reason}" if ref.reason else ""))
            if res.unmeasured_reason:
                print(f"   не измерено: {res.unmeasured_reason}")
        return 1 if res.blocked else 0

    tracker = Path(args.tracker_dir) if args.tracker_dir else root / "nimbalyst-local" / "tracker"
    rep = audit(tracker, root=root)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 1 if rep["blocked_cards"] else 0
    t = rep["totals"]
    print(f"карточек {rep['cards']} · с секцией «Что от тебя нужно» "
          f"{rep['cards_with_instruction_section']} · файлов в индексе {rep['files_indexed']}")
    print(f"ссылок {rep['refs']}: разрешается {t[OK]} · НЕ существует {t[MISSING]} "
          f"· не измерено {t[UNCHECKED]}")
    for kind, slot in sorted(rep["by_kind"].items()):
        print(f"   {_KIND_RU.get(kind, kind)}: ok {slot[OK]} · нет {slot[MISSING]} "
              f"· не измерено {slot[UNCHECKED]}")
    for item in rep["blocked_cards"]:
        print(f"   ❌ {item['card']}: {item['reason']}")
    return 1 if rep["blocked_cards"] else 0


if __name__ == "__main__":  # pragma: no cover — CLI
    raise SystemExit(_main())
