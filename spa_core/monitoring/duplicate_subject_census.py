"""Цена класса «две сессии на одном предмете» — заказ **G38 п. 3** (ADR-413).

Заказ назвал класс и НЕ закрыл его:

    Класс «две сессии на одном предмете» сторожа не имеет. Заявка в
    ``session_changes.jsonl`` остаётся добровольной и никем не читается машинно
    перед взятием работы. Заводить сторожа или признать класс открытым —
    отдельным циклом, **с замером цены**, а не умолчанием.

С тех пор пункт лежит остатком примерно пятьдесят заказов подряд (G38 → G87),
пока ряд закрывал п. 1 за п. 1. Наблюдённый вред записан дважды: цикл #710 —
одну карточку взяли ЧЕТЫРЕ сессии подряд, каждая довела работу до зелёных
тестов и умерла до пуша; раньше — #702…#706, пять циклов подряд.

## Две оси, и ни одна не заменяет другую

===== ================================ ==========================================
ось   вопрос                           чем меряется
===== ================================ ==========================================
A     ЦЕНА: сколько работы сделано      координата (файл), объявленная ДВУМЯ и
      дважды и не доехало никуда?       более различными сессиями на одном
                                        предмете, + её наличие на базовом ref
B     ПОЧЕМУ никто не остановил:        взятия предмета (``card_state: claim``)
      наблюдаемо ли обращение к         против квитанций сторожа захвата
      сторожу захвата?                  (``[check_card_claim]`` в журнале)
===== ================================ ==========================================

Ось A отвечает «сколько это стоило», ось B — «что именно не сработало».
Одной оси мало в обе стороны: ось A без оси B назвала бы цену, не назвав
рычага, а ось B без оси A доложила бы про отсутствующую проводку, не имея
права утверждать, что она хоть чего-нибудь стоит.

## Почему предмет мерится КООРДИНАТОЙ, а не числом сессий на карточке

«Предметов с двумя и более сессиями» в журнале десятки, и это число ценой
класса НЕ является: стоячий приказ владельца по инварианту #14 остаётся
``in-progress`` вечно, и сто шестьдесят сессий подряд на нём — не столкновение,
а передача. Прибор, считающий сессии на карточке, ответил бы на СВОЙ вопрос.
Дважды сделанная работа видна на КООРДИНАТЕ: две сессии объявили один и тот же
файл — значит обе его писали.

## Третий исход обязателен (инв. #17), и здесь их пять

* **журнала нет / не читается** ⇒ ``UNMEASURED``, код 2;
* **запись без предмета** (``card`` не назван) — считается отдельно, а не
  пропадает: у 566 записей из 2295 предмета нет вовсе, и это цена самой формы
  записи, а не ноль;
* **личность сессии без долгоживущего якоря** (``session_pid`` +
  ``session_pid_start``) — считается отдельно. Ярлык (``cycle-6648``) личностью
  НЕ является: он выводится из pid однократной CLI-команды, поэтому у одной
  сессии их бывает несколько, и считать их разными сессиями значило бы
  изготовить столкновение из формы записи;
* **координата не приводится к пути репозитория** — считается отдельно;
* **базовый ref СТАРШЕ объявления** ⇒ о такой координате прибор не судит
  вовсе: «на базе нет» про работу, объявленную позже самой базы, есть
  утверждение о ref'е, а не о работе.

## Одностороннее в этом замере названо заранее

* **«на базе нет» есть утверждение об ОБЪЯВЛЕННОМ ИМЕНИ, а не о работе.**
  У исследовательского слоя имя результата меняется на ходу (замер #243:
  объявлен ``edge_risk_shape_budget.py``, доставлен ``edge_cash_sleeve_frontier.py``),
  поэтому у каждой отсутствующей координаты спрашивается РОДНЯ — файл в том же
  каталоге, делящий с объявленным именем не менее :data:`_KIN_TOKENS` первых
  токенов. Родня есть ⇒ ``absent_kin``: подозрение на переименование, в цену
  НЕ идёт. Родни нет ⇒ ``absent_lost``, и это сильная сторона замера: работа
  под объявленным именем не приехала.
* **ЦЕНА — нижняя граница.** Сессия, не объявившая владение вовсе, в население
  не входит; сессия, объявившая владение без предмета, — тоже.
* **Квитанции у read-only проверки НЕТ ПО ПОСТРОЕНИЮ.** След пишет только
  подкоманда ``claim`` (``announce_claim``); ``check`` не оставляет ничего.
  Поэтому «квитанции нет» НЕ значит «сторожа не спрашивали» — значит, что
  ответить на это нечем, и ровно это отсутствие делает цену класса
  неизмеримой изнутри. Прибор говорит именно так.

## Что этот замер НЕ утверждает

* что все две сессии на одной координате — обязательно потеря: работа могла
  быть передана осознанно (#710 именно так и поднял чужое дерево);
* что журнал полон: он добровольный, и полноту его прибор не проверяет;
* что сторож захвата плох. Он рабочий; предмет здесь — его ЧИТАТЕЛЬ.

Прибор только ЧИТАЕТ: журнал объявлений и дерево базового ref. Ни один порог,
живой трек, RiskPolicy, стоп-кран и ``landing/`` не трогаются. LLM запрещён.
Только stdlib, сети нет (``git ls-tree`` локален, ``fetch`` не вызывается).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import collections
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ARTIFACT_NAME = "duplicate_subject_census.json"
JOURNAL_NAME = "session_changes.jsonl"

#: Базовый ref, на котором спрашивается «эта координата доехала?». Именно
#: `origin/main`, а не `HEAD`: у прод-дерева локальная голова отстаёт от origin
#: по построению (пуши идут через API, минуя индекс), и `HEAD` ответил бы про
#: дерево, которого на origin никогда не было.
DEFAULT_BASE_REF = "origin/main"

#: Сколько первых токенов имени обязана делить РОДНЯ, чтобы отсутствующая
#: координата считалась переименованной, а не потерянной. Три — замер, а не
#: вкус: `test_tracker_board_composition.py` против
#: `test_tracker_board_matches_cards.py` делит ровно три (`test`, `tracker`,
#: `board`) и переименованием быть может, а `ADR-154-unmeasured-origin-sweep`
#: против `ADR-154-contracts-before-orchestration` делит два (`ADR`, `154`) —
#: номер ADR переиспользован другим циклом, и объявленного документа не
#: существует. Порог 2 объявил бы второй случай переименованием и стёр бы
#: настоящую потерю.
_KIN_TOKENS = 3

#: Окно, в котором меряется ПРОВОДКА (ось B). Цена (ось A) считается за всю
#: историю журнала: она уже потрачена и задним числом не меняется. А вопрос
#: «оставляет ли взятие квитанцию» — про сегодняшний порядок работы, и
#: отвечать на него записями двухмесячной давности значило бы держать карточку
#: открытой за поведение, которое уже могло измениться.
_WINDOW_DAYS = 30

STATUS_OPEN = "CLASS_OPEN"
STATUS_CLOSED = "CLASS_CLOSED"
STATUS_UNMEASURED = "UNMEASURED"

#: Префикс, которым сторож захвата подписывает свою запись в журнале
#: (`scripts/check_card_claim.py::announce_claim`). Литерал, а не шаблон:
#: перечень форм обязан оставаться ЗАКРЫТЫМ — вычисляемое имя не гадается.
_RECEIPT_PREFIX = "[check_card_claim]"

#: Функции, вызов которых с литералом-именем и есть ЗАГРУЗКА чужого кода.
#: Перечень ЗАКРЫТ: см. docstring :func:`measure_guard_wiring`.
_LOADING_CALLS = frozenset({
    "spec_from_file_location", "exec_module", "import_module", "load_module",
    "run_path", "run", "Popen", "check_call", "check_output", "system", "exec",
})


# ───────────────────────────── чтение журнала ─────────────────────────────

def load_journal(path: Path) -> Dict[str, Any]:
    """Записи журнала объявлений. ``measured=False`` = журнала нет / не читается."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"measured": False, "reason": f"журнала нет: {path}", "records": []}
    except OSError as exc:
        return {"measured": False, "reason": f"журнал не прочитан: {exc}", "records": []}

    records: List[Dict[str, Any]] = []
    unparsed = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            unparsed += 1
            continue
        if isinstance(doc, dict) and isinstance(doc.get("ts"), str):
            records.append(doc)
        else:
            unparsed += 1
    if not records:
        return {"measured": False,
                "reason": f"в журнале {path} нет ни одной разобранной записи",
                "records": [], "unparsed_lines": unparsed}
    return {"measured": True, "reason": None, "records": records,
            "unparsed_lines": unparsed}


def subject_of(record: Any) -> Optional[str]:
    """Предмет записи — идентификатор карточки, или ``None``, если не назван."""
    raw = observed(record, "card", kind=str)
    if raw is None:
        return None
    name = raw.strip().replace("\\", "/").split("/")[-1]
    if name.endswith(".md"):
        name = name[:-3]
    return name or None


def anchor_of(record: Any) -> Optional[Tuple[int, str]]:
    """Личность сессии — ПАРА долгоживущего процесса, или ``None``.

    Ярлык (``session``) личностью не является намеренно: он выводится из pid
    однократной CLI-команды, поэтому у одной сессии их бывает несколько
    (та самая авария «сессия отказала сама себе», цикл #54). Пары нет ⇒
    личность НЕ ИЗМЕРЕНА, и запись в осях личности не участвует.
    """
    pid = observed(record, "session_pid", kind=int)
    start = observed(record, "session_pid_start", kind=str)
    if pid is None or start is None or not start.strip():
        return None
    return (int(pid), start.strip())


# ────────────────────────── дерево базового ref ───────────────────────────

def read_base_tree(repo_root: Path, ref: str = DEFAULT_BASE_REF) -> Dict[str, Any]:
    """Состав дерева базового ref + его sha и дата. Сети НЕ трогает."""
    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(repo_root),
                              capture_output=True, text=True, timeout=120)

    try:
        head = _git("rev-parse", ref)
        listing = _git("ls-tree", "-r", "--name-only", ref)
        stamp = _git("log", "-1", "--format=%cI", ref)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"measured": False, "reason": f"git не отработал: {exc}"}
    if head.returncode != 0 or listing.returncode != 0:
        return {"measured": False,
                "reason": f"ref {ref} не прочитан: {(head.stderr or listing.stderr).strip()[:200]}"}
    paths = {line.strip() for line in listing.stdout.splitlines() if line.strip()}
    if not paths:
        # Положительный контроль самого прохода: дерево репозитория пустым не
        # бывает, поэтому пустой ответ есть поломка чтения, а не «ничего не
        # доехало». Иначе слепой проход объявил бы потерянным ВСЁ.
        return {"measured": False, "reason": f"дерево ref {ref} пусто — чтение не состоялось"}
    return {"measured": True, "reason": None, "ref": ref,
            "sha": head.stdout.strip(), "committed_at": stamp.stdout.strip() or None,
            "paths": paths,
            "top_level": {p.split("/")[0] for p in paths}}


def normalise(declared: str, top_level: Iterable[str]) -> Optional[str]:
    """Объявленный абсолютный путь → координата репозитория, или ``None``.

    Объявления приходят из ОДНОРАЗОВЫХ деревьев (``/tmp/spa_c715/...``), и
    приставка у каждого своя. Координата берётся как хвост, начинающийся с
    существующего каталога верхнего уровня, — то есть по ДЕРЕВУ, а не по
    догадке о форме приставки.
    """
    text = str(declared).replace("\\", "/").strip()
    if not text:
        return None
    parts = [p for p in text.split("/") if p not in ("", ".")]
    tops = set(top_level)
    for index, segment in enumerate(parts):
        if segment in tops:
            return "/".join(parts[index:])
    return None


def _tokens(name: str) -> List[str]:
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return [t for t in stem.replace("-", "_").split("_") if t]


def kin_of(coordinate: str, base_paths: Iterable[str]) -> List[str]:
    """Родня координаты — файлы того же каталога с общим началом имени.

    Порог общих токенов — :data:`_KIN_TOKENS`, но не больше, чем токенов в
    самом имени: у двухтокенного имени (``orphan_runs.py``) роднёй считается
    только файл, делящий ОБА токена, иначе короткое имя не могло бы иметь
    родни вовсе, и переименование у него было бы недостижимо по построению.
    """
    directory, _, leaf = coordinate.rpartition("/")
    mine = _tokens(leaf)
    if not mine:
        return []
    need = min(_KIN_TOKENS, len(mine))
    kin: List[str] = []
    for path in base_paths:
        other_dir, _, other_leaf = path.rpartition("/")
        if other_dir != directory or other_leaf == leaf:
            continue
        theirs = _tokens(other_leaf)
        shared = 0
        for left, right in zip(mine, theirs):
            if left != right:
                break
            shared += 1
        if shared >= need:
            kin.append(path)
    return sorted(kin)


# ───────────────────────── ось A: цена по координате ──────────────────────

def _dropped_coordinates(records: Sequence[Dict[str, Any]],
                         top_level: Iterable[str]) -> Dict[str, str]:
    """Координаты, про которые сессия ЗАЯВИЛА «не доставляю», и причина.

    Такое объявление есть решение, а не потеря: его читают уборщик деревьев и
    шаг 0a. Причина обязательна — объявление без причины снятием не считается.
    """
    dropped: Dict[str, str] = {}
    for record in records:
        for item in (observed(record, "dropped", kind=list) or []):
            if not isinstance(item, dict):
                continue
            reason = str(item.get("reason") or "").strip()
            coordinate = normalise(str(item.get("path") or ""), top_level)
            if coordinate and reason:
                dropped[coordinate] = reason
    return dropped


def measure_price(records: Sequence[Dict[str, Any]], base: Dict[str, Any]) -> Dict[str, Any]:
    """Ось A: координаты, объявленные ДВУМЯ и более различными сессиями."""
    top_level = base["top_level"]
    base_paths = base["paths"]
    base_dirs = {p.rsplit("/", 1)[0] for p in base_paths if "/" in p}
    base_at = base.get("committed_at") or ""
    dropped = _dropped_coordinates(records, top_level)

    declarations: Dict[Tuple[str, str], Dict[str, Any]] = {}
    no_subject = no_anchor = unnormalised = 0
    for record in records:
        subject = subject_of(record)
        if subject is None:
            no_subject += 1
            continue
        anchor = anchor_of(record)
        if anchor is None:
            no_anchor += 1
            continue
        for declared in (observed(record, "files", kind=list) or []):
            coordinate = normalise(str(declared), top_level)
            if coordinate is None:
                unnormalised += 1
                continue
            slot = declarations.setdefault((subject, coordinate),
                                          {"anchors": {}, "first": record["ts"]})
            slot["anchors"].setdefault(anchor, record["ts"])
            slot["first"] = min(slot["first"], record["ts"])

    findings: List[Dict[str, Any]] = []
    buckets: "collections.Counter[str]" = collections.Counter()
    for (subject, coordinate), slot in sorted(declarations.items()):
        if len(slot["anchors"]) < 2:
            continue
        if coordinate in dropped:
            buckets["declared_dropped"] += 1
            continue
        if coordinate in base_dirs:
            # Объявлен КАТАЛОГ, а не файл: о доставке такого объявления
            # сказать нечего, и подставлять «на базе нет» было бы ложью.
            buckets["declared_a_directory"] += 1
            continue
        if coordinate in base_paths:
            verdict = "at_base"
        elif base_at and slot["first"] > base_at:
            verdict = "base_ref_older_than_declaration"
        else:
            verdict = "absent_kin" if kin_of(coordinate, base_paths) else "absent_lost"
        buckets[verdict] += 1
        if verdict in ("absent_lost", "absent_kin"):
            findings.append({
                "subject": subject, "coordinate": coordinate, "verdict": verdict,
                "sessions": len(slot["anchors"]),
                "first_declared": slot["first"],
                "kin": kin_of(coordinate, base_paths)[:3],
            })

    lost = [f for f in findings if f["verdict"] == "absent_lost"]
    sessions_on_lost = set()
    for (subject, coordinate), slot in declarations.items():
        if any(f["subject"] == subject and f["coordinate"] == coordinate for f in lost):
            sessions_on_lost |= set(slot["anchors"])
    findings.sort(key=lambda f: (-f["sessions"], f["subject"], f["coordinate"]))
    return {
        "coordinates_declared": len(declarations),
        "coordinates_shared_by_two_or_more": sum(buckets.values()),
        "by_verdict": dict(sorted(buckets.items())),
        "lost_coordinates": len(lost),
        "sessions_on_lost_coordinates": len(sessions_on_lost),
        "subjects_on_lost_coordinates": len({f["subject"] for f in lost}),
        "records_without_subject": no_subject,
        "records_without_durable_anchor": no_anchor,
        "declarations_not_normalisable": unnormalised,
        "findings": findings[:40],
    }


# ──────────────────── ось B: квитанция сторожа у взятия ───────────────────

def _parse_ts(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def measure_receipts(records: Sequence[Dict[str, Any]], *,
                     now: Optional[datetime] = None,
                     window_days: int = _WINDOW_DAYS) -> Dict[str, Any]:
    """Ось B: у каждого ли ВЗЯТИЯ предмета есть квитанция сторожа захвата.

    Время — ВХОД, а не окружение: окно считается от переданного ``now``,
    поэтому тест закрепляет обе стороны и не краснеет от сдвига календаря.
    """
    now = now or datetime.now(timezone.utc)
    edge = now - timedelta(days=window_days)

    receipts: set[Tuple[Tuple[int, str], str]] = set()
    for record in records:
        summary = str(observed(record, "summary", kind=str) or "")
        anchor = anchor_of(record)
        subject = subject_of(record)
        if anchor is not None and subject is not None and summary.startswith(_RECEIPT_PREFIX):
            receipts.add((anchor, subject))

    takings = 0
    without = 0
    unparsed_ts = 0
    examples: List[Dict[str, Any]] = []
    seen: set[Tuple[Tuple[int, str], str]] = set()
    for record in records:
        if str(observed(record, "card_state", kind=str) or "claim") != "claim":
            continue
        subject = subject_of(record)
        anchor = anchor_of(record)
        if subject is None or anchor is None:
            continue
        stamp = _parse_ts(record["ts"])
        if stamp is None:
            unparsed_ts += 1
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if stamp < edge:
            continue
        key = (anchor, subject)
        if key in seen:
            continue
        seen.add(key)
        takings += 1
        if key not in receipts:
            without += 1
            if len(examples) < 20:
                examples.append({"subject": subject, "anchor_pid": anchor[0],
                                 "at": record["ts"]})
    return {
        "window_days": window_days,
        "window_from": edge.isoformat().replace("+00:00", "Z"),
        "receipts_in_journal": len(receipts),
        "window_takings": takings,
        "window_takings_without_receipt": without,
        "timestamps_unparsed": unparsed_ts,
        # «Квитанции нет» и «сторожа не спрашивали» — РАЗНЫЕ утверждения, и
        # второе из первого не следует: read-only `check` следа не оставляет.
        "absence_means": ("обращение к сторожу НЕ НАБЛЮДАЕМО: след пишет только "
                          "подкоманда `claim`, а `check` не оставляет ничего"),
        "examples": examples,
    }


def measure_guard_wiring(repo_root: Path) -> Dict[str, Any]:
    """Проводка сторожа захвата, измеренная по ФОРМЕ ВЫЗОВА, а не по имени.

    Упоминание — не вызов, и разница здесь не педантизм: в дереве десять файлов
    называют `check_card_claim`, а грузят его код ДВА. Остальные восемь говорят
    о нём в прозе — комментарием, docstring'ом, строкой подсказки читателю.
    Прибор, считающий упоминания, доложил бы о проводке, которой нет.

    Перечень форм ЗАКРЫТ (урок ADR-468/469) и содержит ровно три:

    * ``import check_card_claim`` / ``from check_card_claim import …`` — загрузка;
    * строковый литерал с этим именем внутри вызова ЗАГРУЖАЮЩЕЙ функции
      (:data:`_LOADING_CALLS`) — так грузит ``spec_from_file_location`` у шага
      0a-ГОЛОД: путь там собирается из литерала выражением, поэтому смотрится
      всё поддерево аргументов;
    * литерал в ЛЮБОМ другом месте — подсказка читателю в ``lines.append``,
      объявление исполнителя в данных картографа, комментарий внутри plist, —
      **НЕ ИЗМЕРЕНО**, исполняется он или нет: прибор не следует ни за
      данными, ни за не-python файлами, и подставлять здесь «да» или «нет»
      запрещено.

    Перечень загружающих функций тоже ЗАКРЫТ, и это существенно: первая
    редакция считала загрузкой литерал внутри ЛЮБОГО вызова, и
    ``lines.append("> Ставится scripts/check_card_claim.py claim …")`` —
    подсказка в тексте доски — сошла за проводку. Вычисляемое имя модуля не
    гадается: литерала нет ⇒ форма не опознана.

    **Чего этот замер НЕ утверждает:** что загрузивший ЧИТАЕТ ВЕРДИКТ. Один из
    двух грузит ровно одну константу (`_CLAIM_KEYS` в `check_tracker_drift`), и
    к вопросу «эту карточку уже взяли?» это отношения не имеет.
    """
    needle = "check_card_claim"
    loads: List[str] = []
    unfollowed_mentions: List[str] = []
    prose_only: List[str] = []
    scanned = 0
    for folder in ("scripts", "spa_core", "launchd", ".github"):
        root = repo_root / folder
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".sh", ".yml", ".yaml", ".plist"):
                continue
            rel = path.relative_to(repo_root).as_posix()
            if "/tests/" in f"/{rel}" or rel.rsplit("/", 1)[-1].startswith("test_"):
                continue
            if rel == "scripts/check_card_claim.py":
                continue
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if needle not in text:
                continue
            if path.suffix != ".py":
                unfollowed_mentions.append(rel)
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                prose_only.append(rel)
                continue
            in_loading_call: set[int] = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func
                name = (callee.attr if isinstance(callee, ast.Attribute)
                        else callee.id if isinstance(callee, ast.Name) else "")
                if name not in _LOADING_CALLS:
                    continue
                for kid in ast.walk(node):
                    in_loading_call.add(id(kid))
            loaded = False
            literal_outside_call = False
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in getattr(node, "names", [])]
                    if getattr(node, "module", None) == needle or needle in names:
                        loaded = True
                elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and needle in node.value:
                    if id(node) in in_loading_call:
                        loaded = True
                    else:
                        literal_outside_call = True
            if loaded:
                loads.append(rel)
            elif literal_outside_call:
                unfollowed_mentions.append(rel)
            else:
                prose_only.append(rel)
    if scanned == 0:
        return {"measured": False, "reason": "ни одного файла дерева не осмотрено",
                "loads": [], "unfollowed_mentions": [], "prose_only": [], "files_scanned": 0}
    return {"measured": True, "reason": None, "loads": sorted(loads),
            "unfollowed_mentions": sorted(unfollowed_mentions), "prose_only": sorted(prose_only),
            "mentions": len(loads) + len(unfollowed_mentions) + len(prose_only),
            "files_scanned": scanned}


# ─────────────────────────────── сборка ──────────────────────────────────

def run_census(data_dir: Path, *, repo_root: Path,
               base_ref: str = DEFAULT_BASE_REF,
               now: Optional[datetime] = None,
               window_days: int = _WINDOW_DAYS) -> Dict[str, Any]:
    """Отчёт переписи. ``measured=False`` ⇒ вердикта нет вовсе."""
    stamp = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    report: Dict[str, Any] = {
        "generated_at": stamp,
        "order": "G38 п. 3 (ADR-413) — цена класса «две сессии на одном предмете»",
        "measured": False,
        "status": STATUS_UNMEASURED,
        "reason": None,
        # Форма отчёта ПОСТОЯННА: ключи объявлены всегда, а «не вычислено»
        # представлено `None`, а не отсутствием ключа. Иначе шаг 0-офис не
        # отличил бы «производитель уехал и перестал писать поле» от «в этот раз
        # поле не считалось» — и объявленная схема артефакта перестала бы быть
        # измерением (инв. #17).
        "base_ref": None,
        "price": None,
        "receipts": None,
        "guard_wiring": None,
    }

    journal = load_journal(data_dir / JOURNAL_NAME)
    report["journal"] = {"records": len(journal["records"]),
                         "unparsed_lines": journal.get("unparsed_lines", 0)}
    if not journal["measured"]:
        report["reason"] = journal["reason"]
        return report

    base = read_base_tree(repo_root, base_ref)
    if not base["measured"]:
        report["reason"] = base["reason"]
        report["base_ref"] = {"ref": base_ref, "measured": False}
        return report
    report["base_ref"] = {"ref": base["ref"], "sha": base["sha"],
                          "committed_at": base["committed_at"],
                          "files": len(base["paths"]), "measured": True}

    price = measure_price(journal["records"], base)
    if price["coordinates_declared"] == 0:
        # Слепой проход (приставка не распознана ни у одной записи) выглядел бы
        # как «дважды сделанной работы нет». Это НЕ ИЗМЕРЕНО, и громко.
        report["reason"] = ("ни одна объявленная координата не приведена к пути "
                            "репозитория — приставка деревьев не распознана")
        report["price"] = price
        return report
    receipts = measure_receipts(journal["records"], now=now, window_days=window_days)
    wiring = measure_guard_wiring(repo_root)
    report["price"] = price
    report["receipts"] = receipts
    report["guard_wiring"] = wiring

    if receipts["window_takings"] == 0:
        # Вырожденный проход: окно пусто ⇒ «у всех взятий есть квитанция»
        # верно ПО ПОСТРОЕНИЮ и ответом не является.
        report["reason"] = (f"в окне {window_days} дн. ни одного взятия предмета — "
                            "проводка не измерена, а не исправна")
        return report

    report["measured"] = True
    report["status"] = (STATUS_OPEN
                        if receipts["window_takings_without_receipt"] > 0
                           or price["lost_coordinates"] > 0
                        else STATUS_CLOSED)
    return report


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if not report.get("measured"):
        lines.append(f"цена класса «две сессии на одном предмете»: НЕ ИЗМЕРЕНО — "
                     f"{report.get('reason')}")
        return lines
    price = report["price"]
    receipts = report["receipts"]
    wiring = report["guard_wiring"]
    lines.append(
        f"цена класса «две сессии на одном предмете» (заказ G38 п. 3): {report['status']} · "
        f"координат у двух и более сессий {price['coordinates_shared_by_two_or_more']} · "
        f"ПОТЕРЯНО {price['lost_coordinates']} · "
        f"сессий на потерянных координатах {price['sessions_on_lost_coordinates']}")
    lines.append("[ОСЬ A] по вердикту: " + " · ".join(
        f"{k} {v}" for k, v in price["by_verdict"].items()))
    lines.append(
        f"[ОСЬ B] взятий предмета за {receipts['window_days']} дн. "
        f"{receipts['window_takings']}, БЕЗ квитанции сторожа "
        f"{receipts['window_takings_without_receipt']}; квитанций в журнале всего "
        f"{receipts['receipts_in_journal']}")
    lines.append(f"[ОСЬ B] {receipts['absence_means']}")
    if not wiring["measured"]:
        lines.append(f"[ПРОВОДКА] НЕ ИЗМЕРЕНО — {wiring['reason']}")
    else:
        lines.append(
            f"[ПРОВОДКА] сторожа захвата НАЗЫВАЮТ {wiring['mentions']} файл(ов) вне тестов, "
            f"а ГРУЗЯТ {len(wiring['loads'])}: {', '.join(wiring['loads']) or '—'}; "
            f"упоминаний, за которыми прибор НЕ СЛЕДУЕТ (исполнение НЕ ИЗМЕРЕНО) "
            f"{len(wiring['unfollowed_mentions'])}; только проза {len(wiring['prose_only'])}")
    for finding in price["findings"][:8]:
        lines.append(f"[{finding['verdict']}] сессий {finding['sessions']} · "
                     f"{finding['subject']} :: {finding['coordinate']}"
                     + (f" · родня {finding['kin'][0]}" if finding["kin"] else ""))
    lines.append("НЕ ДОКЛАДЫВАЕТ: полноту добровольного журнала · были ли две сессии "
                 "передачей или переделкой · верность самого сторожа захвата")
    lines.append("ADVISORY: пороги RiskPolicy v1.0, стоп-кран, аллокатор, живой трек и "
                 "landing/ НЕ трогаются — прибор только ЧИТАЕТ журнал и дерево базового ref")
    return lines


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с
    названной причиной обязано доехать до читателя, иначе шаг 0-офис увидит
    отсутствие файла и не отличит его от «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    data_dir = repo_root / "data"
    report = run_census(data_dir, repo_root=repo_root, now=now)
    try:
        save_artifact(report, data_dir)
    except Exception as exc:  # noqa: BLE001 — перепись не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", default=None, help="каталог данных (по умолчанию — свой)")
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — свой)")
    ap.add_argument("--base-ref", default=DEFAULT_BASE_REF, help="базовый ref доставки")
    ap.add_argument("--window-days", type=int, default=_WINDOW_DAYS)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать {ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    data_dir = Path(args.data_dir) if args.data_dir else (repo_root / "data")
    report = run_census(data_dir, repo_root=repo_root, base_ref=args.base_ref,
                        window_days=args.window_days)
    if args.save:
        save_artifact(report, data_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)
    if not report.get("measured"):
        return 2
    return 1 if report["status"] == STATUS_OPEN else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
