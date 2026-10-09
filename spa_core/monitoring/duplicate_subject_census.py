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
C     КАКОЙ ДВЕРЬЮ объявлено взятие     те же взятия, разложенные на закрытое
      (заказ G110 п. 2)                 разбиение «только сторож · обе ·
                                        только писатель», с опровержимым
                                        тождеством против числа оси B
D     НАЗЫВАЕТ ли дверь-квитанцию       литерал ``check_card_claim.py claim``
      сама ИНСТРУКЦИЯ (G110 п. 2)       в ТЕЛЕ промпта цикла и в документе
                                        протокола
===== ================================ ==========================================

## Почему ось C не есть ось B другими словами

Ось B печатает ОДНО число, и заголовочным оно читается как «сторожа не
спрашивали». Квитанцию оставляет только подкоманда ``claim``; read-only
``check`` не оставляет ничего — замерено исходом (ADR-535, ответ 3). Значит
«без квитанции» есть ровно «объявлено НЕ дверью сторожа»: замер ДВЕРИ, а не
вопроса. Ось C называет это двумя числами, ось D спрашивает, чьё это свойство —
сессий или инструкции, которая дверь-квитанцию может и не называть.

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


def tree_prefix_of(declared: str, top_level: Iterable[str]) -> Optional[str]:
    """Приставка ДЕРЕВА, в котором работа объявлена, или ``None``.

    Обратная половина :func:`normalise`: та отрезает приставку, чтобы получить
    координату репозитория, а здесь нужна именно приставка — чтобы спросить,
    существует ли ещё дерево, из которого работу можно ПОДНЯТЬ. Объявление
    бывает и без приставки (сессия назвала путь относительно репозитория) — это
    не ошибка и не отсутствие дерева, а ТРЕТИЙ исход: дерево не названо.
    """
    text = str(declared).replace("\\", "/").strip()
    if not text:
        return None
    parts = [p for p in text.split("/") if p not in ("", ".")]
    tops = set(top_level)
    for index, segment in enumerate(parts):
        if segment in tops:
            if index == 0:
                return None
            prefix = "/".join(parts[:index])
            return "/" + prefix if text.startswith("/") else prefix
    return None


def _tokens(name: str) -> List[str]:
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return [t for t in stem.replace("-", "_").split("_") if t]


def _shared_prefix(mine: Sequence[str], theirs: Sequence[str]) -> int:
    shared = 0
    for left, right in zip(mine, theirs):
        if left != right:
            break
        shared += 1
    return shared


def _numbered(tokens: Sequence[str]) -> Optional[Tuple[str, List[str]]]:
    """Имя вида ``<слово>-<число>-<слаг>`` → (слово, слаг). Иначе ``None``.

    Нужно ровно для нумерованных документов (``ADR-366-…``): у них ПЕРВЫЕ
    токены — марка и номер, а предмет лежит ЗА номером, и сравнение по началу
    имени до него не доходит никогда.
    """
    if len(tokens) < 3 or not tokens[1].isdigit() or tokens[0].isdigit():
        return None
    return tokens[0], list(tokens[2:])


def kin_of(coordinate: str, base_paths: Iterable[str]) -> List[str]:
    """Родня координаты — файлы того же каталога с общим началом имени.

    Порог общих токенов — :data:`_KIN_TOKENS`, но не больше, чем токенов в
    самом имени: у двухтокенного имени (``orphan_runs.py``) роднёй считается
    только файл, делящий ОБА токена, иначе короткое имя не могло бы иметь
    родни вовсе, и переименование у него было бы недостижимо по построению.

    **Вторая дверь — СЛАГ нумерованного документа, и без неё мера односторонне
    завышала цену.** Замер #751: объявленный ``ADR-365-capital-observability-
    over-history.md`` лежит на базе как ``ADR-366-capital-observability-over-
    history.md`` — переномерован перед пушем, потому что номер 365 за сутки
    сиротства занял другой цикл (сказано дословно в сообщении того коммита,
    ``32e03c3a5``). Сравнение по НАЧАЛУ имени такую родню увидеть не может по
    построению: токены расходятся на номере, то есть вторыми, и дальше первого
    совпадения мера не идёт. Документ был ДОСТАВЛЕН, а перепись звала его
    потерей и посылала следующую сессию поднимать уже сделанную работу.

    Односторонность правила номера при этом сохранена, и ровно она разводит два
    случая: ``ADR-154-unmeasured-origin-sweep-and-board-composition`` против
    лежащего на базе ``ADR-154-contracts-before-orchestration`` — тот же номер,
    но слаг не делит НИ ОДНОГО токена, то есть номер переиспользован другим
    циклом, а объявленного документа не существует. Это остаётся потерей.
    """
    directory, _, leaf = coordinate.rpartition("/")
    mine = _tokens(leaf)
    if not mine:
        return []
    need = min(_KIN_TOKENS, len(mine))
    mine_numbered = _numbered(mine)
    kin: List[str] = []
    for path in base_paths:
        other_dir, _, other_leaf = path.rpartition("/")
        if other_dir != directory or other_leaf == leaf:
            continue
        theirs = _tokens(other_leaf)
        if _shared_prefix(mine, theirs) >= need:
            kin.append(path)
            continue
        theirs_numbered = _numbered(theirs)
        if mine_numbered is None or theirs_numbered is None:
            continue
        if mine_numbered[0] != theirs_numbered[0]:
            continue
        my_slug, their_slug = mine_numbered[1], theirs_numbered[1]
        slug_need = min(_KIN_TOKENS, len(my_slug))
        if _shared_prefix(my_slug, their_slug) >= slug_need:
            kin.append(path)
    return sorted(kin)


#: Что означает отсутствие координаты на базе, когда база ПОМНИТ её удаление.
#: Замер #751: `scripts/day30_review.py` объявили две сессии 19.08 (#301 и
#: #302) — и обе объявили его, чтобы СПИСАТЬ обёртку. Удаление доставлено
#: коммитом `d45cb4a3c` того же дня, а замену (`python3 -m
#: spa_core.riskwire.day30_review`) закрепил тест `test_day30_review_cli_contract.py`,
#: лежащий на базе. Перепись читала ту же пустоту как потерю: чем успешнее
#: доставлено списание, тем больше оно похоже на пропавшую работу. Односторонне
#: и в опасную сторону — следующую сессию посылали ВЕРНУТЬ файл, то есть
#: отменить решение.
def retirement_door(repo_root: Path, ref: str):
    """Замыкание «помнит ли база удаление этой координаты».

    **Отказ здесь АСИММЕТРИЧЕН, и это замер, а не осторожность.** Обрезанная
    история (`.git/shallow`) не мешает УВИДЕТЬ удаление: если коммит достижим,
    он достижим. Мешает она ровно обратному — заключить, что удаления НЕ БЫЛО:
    `git log` по пути в обрезанном дереве честно отдаёт пустоту и код 0, и
    прочесть эту пустоту как «не удалялось» значило бы объявить потерей каждое
    доставленное списание. Замер прод-дерева #751: 443 достижимых коммита при
    20 точках обрезки, удаляющий коммит `d45cb4a3c` в дереве ЛЕЖИТ (объект
    есть), а обходом не достигается — пустой ответ при существующем удалении.

    Поэтому: нашли удаление ⇒ ИЗМЕРЕНО · не нашли в полном клоне ⇒ ИЗМЕРЕНО и
    равно нулю · не нашли в обрезанном ⇒ НЕ ИЗМЕРЕНО с названной причиной.
    """
    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=str(repo_root),
                              capture_output=True, text=True, timeout=120)

    def _dead(reason: str):
        return lambda coordinate: {"asked": True, "measured": False, "reason": reason,
                                   "deleted_at": None, "sha": None}

    try:
        shallow = _git("rev-parse", "--is-shallow-repository")
    except (OSError, subprocess.SubprocessError) as exc:
        return _dead(f"git не отработал: {exc}")
    if shallow.returncode != 0:
        return _dead(f"глубина клона не прочитана: {shallow.stderr.strip()[:160]}")
    truncated = shallow.stdout.strip() == "true"

    def ask(coordinate: str) -> Dict[str, Any]:
        try:
            log = _git("log", ref, "--diff-filter=D", "-1",
                       "--format=%cI%x09%H", "--", coordinate)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"asked": True, "measured": False, "deleted_at": None, "sha": None,
                    "reason": f"git не отработал: {exc}"}
        if log.returncode != 0:
            return {"asked": True, "measured": False, "deleted_at": None, "sha": None,
                    "reason": f"история пути не прочитана: {log.stderr.strip()[:160]}"}
        line = log.stdout.strip().splitlines()[0] if log.stdout.strip() else ""
        if not line:
            if truncated:
                return {"asked": True, "measured": False, "deleted_at": None, "sha": None,
                        "reason": ("дерево ОБРЕЗАНО (`.git/shallow`): пустой обход не есть "
                                   "отсутствие удаления — нужен полный клон")}
            return {"asked": True, "measured": True, "deleted_at": None, "sha": None,
                    "reason": None}
        stamp, _, sha = line.partition("\t")
        return {"asked": True, "measured": True, "deleted_at": stamp.strip(),
                "sha": sha.strip(), "reason": None}

    return ask


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


def _retirement_verdict(coordinate: str, first_declared: str,
                        retirement) -> Tuple[str, Optional[str]]:
    """Отсутствие на базе: потеря, доставленное СПИСАНИЕ или НЕ ИЗМЕРЕНО.

    Разводит их ОТМЕТКА: удаление ПОЗЖЕ объявления значит, что сессия объявила
    координату, чтобы её убрать, и убрала — работа доехала. Удаление РАНЬШЕ
    объявления ничего не оправдывает: там сессия завела файл заново и не
    доставила, и это по-прежнему потеря. Поэтому сравниваются отметки, а не
    факт «когда-то удалялся».
    """
    if retirement is None:
        return "absent_lost", "not_asked"
    answer = retirement(coordinate)
    if not answer.get("measured"):
        return "absent_retirement_unmeasured", str(answer.get("reason") or "причина не названа")
    deleted_at = answer.get("deleted_at")
    if not deleted_at:
        return "absent_lost", "база удаления этой координаты не помнит"
    left, right = _parse_ts(deleted_at), _parse_ts(first_declared)
    if left is None or right is None:
        return "absent_retirement_unmeasured", f"отметка не разобрана: {deleted_at!r}"
    if left >= right:
        return "retired_at_base", f"списана коммитом {answer.get('sha', '')[:9]} в {deleted_at}"
    return "absent_lost", f"удалена ДО объявления ({deleted_at}) — заведена заново и не доехала"


def _liftability(slot: Dict[str, Any], tree_exists) -> Dict[str, Any]:
    """Цело ли ещё дерево, из которого потерянную работу можно ПОДНЯТЬ.

    Заказ G88 п. 3 велел поднять потерянные координаты, и этого у переписи не
    хватало: цену она называет, а подъёмность — нет. Замер #751: все 11
    объявленных деревьев (`/tmp/spa_c301`…`/tmp/spa_c588`) стёрты, то есть
    приказ «поднять» пришёл через 32 дня после того, как поднимать стало
    нечего. Окно подъёма равно времени жизни `/tmp`, и мерить его обязан тот же
    прибор, что называет цену, — иначе следующая сессия снова узнает об этом
    только своим поиском.

    Три исхода, и третий не склеен ни с одним: дерево ЕСТЬ (поднимать можно и
    путь назван) · дерево стёрто (цена окончательна) · дерево не названо вовсе
    (объявление пришло относительным путём — сказать нечего).
    """
    probe = tree_exists if tree_exists is not None else (lambda path: Path(path).exists())
    trees = sorted(slot.get("trees") or ())
    alive = [t for t in trees if probe(t)]
    if alive:
        state = "tree_present"
    elif trees:
        state = "tree_gone"
    else:
        state = "tree_not_named"
    return {"liftable": state, "trees": trees[:3], "trees_alive": alive[:3]}


def measure_price(records: Sequence[Dict[str, Any]], base: Dict[str, Any], *,
                  retirement=None, tree_exists=None) -> Dict[str, Any]:
    """Ось A: координаты, объявленные ДВУМЯ и более различными сессиями.

    ``retirement`` — дверь «помнит ли база удаление этой координаты»
    (:func:`retirement_door`). ``None`` значит «не спрошено», и такая координата
    остаётся ``absent_lost`` с пометкой ``not_asked``: ошибка идёт в сторону
    ЗАВЫШЕНИЯ цены, а не занижения. Боевой путь (:func:`run_census`) дверь
    передаёт ВСЕГДА, и это закреплено тестом — иначе «не спрошено» стало бы
    тихим fail-OPEN.

    ``tree_exists`` — дверь «цело ли ещё дерево, из которого работу можно
    поднять». Дверь к ОС принимается ВХОДОМ (урок `.claude/rules/deployment.md`
    про личность процесса): иначе тест судил бы о том, что сегодня лежит в
    `/tmp` у этого хоста.
    """
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
                                          {"anchors": {}, "first": record["ts"],
                                           "trees": set(), "trees_unnamed": 0})
            slot["anchors"].setdefault(anchor, record["ts"])
            slot["first"] = min(slot["first"], record["ts"])
            prefix = tree_prefix_of(str(declared), top_level)
            if prefix is None:
                slot["trees_unnamed"] += 1
            else:
                slot["trees"].add(prefix)

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
        retirement_note: Optional[str] = None
        if coordinate in base_paths:
            verdict = "at_base"
        elif base_at and slot["first"] > base_at:
            verdict = "base_ref_older_than_declaration"
        elif kin_of(coordinate, base_paths):
            verdict = "absent_kin"
        else:
            verdict, retirement_note = _retirement_verdict(
                coordinate, slot["first"], retirement)
        buckets[verdict] += 1
        if verdict in ("absent_lost", "absent_kin", "retired_at_base",
                       "absent_retirement_unmeasured"):
            finding = {
                "subject": subject, "coordinate": coordinate, "verdict": verdict,
                "sessions": len(slot["anchors"]),
                "first_declared": slot["first"],
                "kin": kin_of(coordinate, base_paths)[:3],
            }
            if retirement_note is not None:
                finding["retirement"] = retirement_note
            if verdict in ("absent_lost", "absent_retirement_unmeasured"):
                # Подъёмность спрашивается и у «не измерено»: она про ДЕРЕВО,
                # а не про вопрос списания, и на обрезанном клоне (то есть на
                # боевом хосте) иначе не докладывалась бы вовсе — ровно там,
                # где заказ G88 п. 3 её и спрашивает.
                finding.update(_liftability(slot, tree_exists))
            findings.append(finding)

    lost = [f for f in findings if f["verdict"] == "absent_lost"]
    lift = collections.Counter(f["liftable"] for f in findings if "liftable" in f)
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
        "retirement_door_asked": retirement is not None,
        "retirement_unmeasured": buckets.get("absent_retirement_unmeasured", 0),
        "retired_at_base": buckets.get("retired_at_base", 0),
        "liftability": dict(sorted(lift.items())),
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


# ───────── ось C: какой ДВЕРЬЮ объявлено взятие (заказ G110 п. 2) ─────────

#: Двери объявления взятия. Перечень ЗАКРЫТ и состоит из ДВУХ: подкоманда
#: ``claim`` сторожа захвата (``scripts/check_card_claim.py``), чей след в
#: журнале и есть квитанция, и писатель журнала НАПРЯМУЮ
#: (``scripts/log_session_change.py --card-state claim``). Третьей двери нет
#: ПО ПОСТРОЕНИЮ: писатель журнала ровно один (докстринг ``log_session_change``),
#: а сторож пишет через него же — поэтому дверь различима РОВНО приставкой
#: :data:`_RECEIPT_PREFIX`, и «дверь не распознана» обязано быть НЕВОЗМОЖНО, а
#: не редко. Ненулевой счёт такого класса есть поломка разбора, и ось от него
#: отказывается (ниже), а не докладывает долю.
DOOR_GUARD = "guard"
DOOR_WRITER = "writer"


def door_of(summary: str) -> Optional[str]:
    """Дверь, которой оставлена запись, по её приставке. ``None`` = не распознана.

    Настоящее правило ТОТАЛЬНО по построению — ``None`` оно не возвращает
    никогда, и это закреплено контролем. Отказ прибора на нераспознанной двери
    всё равно нужен, потому что правило передаётся ВХОДОМ: тотальность есть
    свойство ПРАВИЛА, а не прибора, и прибор, уверенный в чужом свойстве,
    поделил бы население на неполном разбиении молча.
    """
    return DOOR_GUARD if summary.startswith(_RECEIPT_PREFIX) else DOOR_WRITER


def measure_taking_doors(records: Sequence[Dict[str, Any]], *,
                         receipts: Dict[str, Any],
                         now: Optional[datetime] = None,
                         window_days: int = _WINDOW_DAYS,
                         door: Optional[Any] = None) -> Dict[str, Any]:
    """Ось C: какой ДВЕРЬЮ объявлено взятие предмета — сторожа или писателя.

    Ось B отвечает ОДНИМ числом (``window_takings_without_receipt``), и
    заголовочным оно читается как «сторожа не спрашивали». Это не то, что она
    меряет. Квитанцию оставляет только подкоманда ``claim``; read-only ``check``
    не оставляет НИЧЕГО — замерено исходом (ADR-535, ответ 3: одноразовая сцена,
    sha256 до и после настоящего вызова двери, вердикт ``no_trace``). Значит
    «без квитанции» есть ровно «объявлено НЕ дверью сторожа», то есть замер
    ДВЕРИ, а обращение к сторожу не наблюдаемо ни одним числом ни одной оси.

    Заказ **G110 п. 2** требует назвать это ДВУМЯ числами, и вот они:
    ``through_guard_door`` и ``by_writer_door_only``.

    Ось СОЗНАТЕЛЬНО пересчитывает население взятий, уже посчитанное осью B, и
    это второй экземпляр мерки — тот самый класс, что молча расходится
    (ADR-220). Противоядие здесь не доверие, а **опровержимое тождество**:
    число писательской двери обязано СОВПАСТЬ с ``window_takings_without_receipt``
    соседней оси, иначе ось отказывается (третий исход с названной причиной).
    Поэтому отчёт соседа передаётся ВХОДОМ, а не читается заново.

    Время — ВХОД, а не окружение: окно считается от переданного ``now``.
    """
    now = now or datetime.now(timezone.utc)
    edge = now - timedelta(days=window_days)
    door = door or door_of

    # Сторона сторожа берётся по ВСЕЙ истории журнала — ровно так, как её берёт
    # ось B: квитанция, оставленная за минуту до края окна, квитанцией быть не
    # перестаёт. Сузить её до окна значило бы разойтись с соседом молча.
    guard_keys: set[Tuple[Tuple[int, str], str]] = set()
    for record in records:
        summary = str(observed(record, "summary", kind=str) or "")
        anchor = anchor_of(record)
        subject = subject_of(record)
        if anchor is not None and subject is not None and door(summary) == DOOR_GUARD:
            guard_keys.add((anchor, subject))

    writer_keys: set[Tuple[Tuple[int, str], str]] = set()
    order: List[Tuple[Tuple[Tuple[int, str], str], str]] = []
    seen: set[Tuple[Tuple[int, str], str]] = set()
    unparsed_ts = 0
    without_subject = 0
    subject_without_anchor = 0
    for record in records:
        if str(observed(record, "card_state", kind=str) or "claim") != "claim":
            continue
        stamp = _parse_ts(record["ts"])
        if stamp is None:
            unparsed_ts += 1
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if stamp < edge:
            continue
        subject = subject_of(record)
        anchor = anchor_of(record)
        # ДВА пропуска, и складывать их запрещено. Запись без предмета —
        # обычное объявление владения файлами без карточки: взятием ПРЕДМЕТА
        # она не является ПО ПОСТРОЕНИЮ, и в знаменателе ей делать нечего.
        # Запись с предметом, но без пары долгоживущего процесса, — настоящее
        # взятие, чью дверь приписать НЕКОМУ: личность не измерена (докстринг
        # `anchor_of`). Слить их в одно «не опознано» значило бы спрятать
        # второе за объёмом первого (здесь — 14 за 125).
        if subject is None:
            without_subject += 1
            continue
        if anchor is None:
            subject_without_anchor += 1
            continue
        key = (anchor, subject)
        if key not in seen:
            seen.add(key)
            order.append((key, str(record["ts"])))
        summary = str(observed(record, "summary", kind=str) or "")
        if door(summary) == DOOR_WRITER:
            writer_keys.add(key)

    guard_only = writer_only = both = unrecognised = 0
    unrecognised_examples: List[Dict[str, Any]] = []
    for key, at in order:
        in_guard = key in guard_keys
        in_writer = key in writer_keys
        if in_guard and in_writer:
            both += 1
        elif in_guard:
            guard_only += 1
        elif in_writer:
            writer_only += 1
        else:
            unrecognised += 1
            if len(unrecognised_examples) < 20:
                unrecognised_examples.append({"subject": key[1], "anchor_pid": key[0][0],
                                              "at": at})

    takings = len(order)
    report: Dict[str, Any] = {
        "window_days": window_days,
        "window_from": edge.isoformat().replace("+00:00", "Z"),
        "measured": False,
        "reason": None,
        "window_takings": takings,
        # ДВА числа вместо одного — предмет заказа G110 п. 2. Доля НЕ заменяет
        # ни одно из них: 17 из 280 и 17 из 18 суть разные утверждения.
        "through_guard_door": guard_only + both,
        "by_writer_door_only": writer_only,
        "through_guard_door_pct": None,
        "by_door": {"guard_only": guard_only, "writer_only": writer_only,
                    "both": both, "door_unrecognised": unrecognised},
        "timestamps_unparsed": unparsed_ts,
        "records_without_subject": without_subject,
        "takings_without_measured_identity": subject_without_anchor,
        "axis_b_identity": None,
        "door_unrecognised_examples": unrecognised_examples,
        "measures": ("КАКОЙ дверью объявлено взятие, а НЕ спрашивали ли сторожа: "
                     "read-only `check` следа не оставляет вовсе (ADR-535, ответ 3 — "
                     "замер следа `no_trace`), поэтому обращение к сторожу "
                     "НЕ НАБЛЮДАЕМО ни одним числом ни одной оси"),
    }

    if takings == 0:
        report["reason"] = (f"в окне {window_days} дн. ни одного взятия предмета с "
                            f"измеренной личностью (записей без предмета "
                            f"{without_subject}, взятий без измеренной личности "
                            f"{subject_without_anchor}, метка не разобрана у "
                            f"{unparsed_ts}) — дверь НЕ ИЗМЕРЕНА, а не одна")
        return report
    if unrecognised:
        report["reason"] = (f"у {unrecognised} из {takings} взятий дверь НЕ РАСПОЗНАНА, "
                            f"хотя у настоящего правила это невозможно — переданное "
                            f"правило двери не тотально; доля двери была бы вычислена "
                            f"по неполному населению")
        return report
    # Отдельной проверки «классы складываются в население» здесь НЕТ, и это
    # решение, а не упущение: цикл выше увеличивает РОВНО ОДИН счётчик на
    # каждый ключ, поэтому сумма четырёх классов равна населению по построению,
    # а отказ выше ловит единственный класс, который может быть ненулевым.
    # Ветвь, которая не может сработать, — не сторож, а украшение: мутационный
    # замер пережил её целиком (пять мутантов в ней не меняли ни одного числа),
    # и это тот же дефект «мёртвой ветви», что нашёл цикл #818 в своей оси 1.

    # Опровержимое тождество с соседней осью: «без квитанции» и «объявлено
    # писательской дверью» обязаны быть ОДНИМ И ТЕМ ЖЕ числом. Разошлись ⇒
    # один из двух экземпляров мерки неверен, и который — не угадывается.
    expected = receipts.get("window_takings_without_receipt") if isinstance(receipts, dict) else None
    neighbour_takings = receipts.get("window_takings") if isinstance(receipts, dict) else None
    report["axis_b_identity"] = {"neighbour_without_receipt": expected,
                                 "neighbour_window_takings": neighbour_takings,
                                 "my_writer_door_only": writer_only,
                                 "my_window_takings": takings,
                                 "holds": (expected == writer_only
                                           and neighbour_takings == takings)}
    if not isinstance(expected, int) or not isinstance(neighbour_takings, int):
        report["reason"] = ("отчёт оси B не несёт чисел взятий — сверить второй "
                            "экземпляр мерки нечем, и расхождение осталось бы молчаливым")
        return report
    if not report["axis_b_identity"]["holds"]:
        report["reason"] = (f"тождество с осью B НЕ держится: «без квитанции» "
                            f"{expected} при моих {writer_only} писательских, взятий "
                            f"{neighbour_takings} при моих {takings} — два экземпляра "
                            f"мерки разошлись")
        return report

    report["through_guard_door_pct"] = round(100.0 * (guard_only + both) / takings, 2)
    report["measured"] = True
    return report


# ──── ось D: называет ли ИНСТРУКЦИЯ дверь, оставляющую квитанцию (G110 п. 2) ────

#: Поверхности инструкции. Перечень ЗАКРЫТ, каждая названа путём-литералом и
#: СПОСОБОМ чтения: ``prompt`` — тело присваивания ``PROMPT="…"`` (ровно тот
#: текст, который сессия получает на вход), ``whole`` — файл целиком (документ,
#: который сессии предписано прочитать).
_INSTRUCTION_SURFACES: Tuple[Tuple[str, str, str], ...] = (
    ("prompt_orchestrator", "scripts/agent_orchestrator.sh", "prompt"),
    ("protocol_document", "docs/ORCHESTRATOR_PROTOCOL.md", "whole"),
)

#: Литералы дверей. У сторожа — именно подкоманда ``claim``.
_DOOR_TOKENS: Dict[str, str] = {DOOR_GUARD: "check_card_claim.py claim",
                                DOOR_WRITER: "log_session_change.py"}

#: Отдельно — read-only подкоманда сторожа. Она квитанции НЕ оставляет, поэтому
#: дверью квитанции не является и в классы не идёт; считается, чтобы «названа
#: только `check`» не читалось как «дверь сторожа названа».
_GUARD_CHECK_TOKEN = "check_card_claim.py check"


def _prompt_body(text: str, *,
                 max_steps: Optional[int] = None) -> Tuple[Optional[str], Optional[str]]:
    """Тело присваивания ``PROMPT="…"`` — или причина, по которой его нет.

    Файл целиком на этот вопрос НЕ отвечает: ``scripts/agent_orchestrator.sh``
    называет писателя журнала ещё и в КОММЕНТАРИИ (абзац про долгоживущую
    личность сессии), а комментарий сессии не достаётся. Прибор, считающий
    вхождения в файле, объявил бы дверь названной там, где цикл её не видит —
    ровно «проза, называющая предмет, не есть его производитель».
    """
    offset = 0
    start: Optional[int] = None
    for line in text.splitlines(keepends=True):
        if line.startswith('PROMPT="'):
            start = offset + len('PROMPT="')
            break
        offset += len(line)
    if start is None:
        return None, 'в файле нет строки, начинающейся с `PROMPT="`'

    # Шаг разбора обязан идти ВПЕРЁД, и это ПРОВЕРЯЕТСЯ, а не предполагается.
    # Цикл, чей прогресс лишь подразумевается, мутант не краснит, а ПОДВЕШИВАЕТ:
    # мутационный замер этого прибора дал ровно такой исход на обоих `i += 2`
    # (урок #817 — беззащитная пагинация; урок #465 — в дифференциальном замере
    # такой тест не падает и не проходит, он ИСЧЕЗАЕТ). Потолок — ВХОД, по
    # умолчанию длина самого текста: больше шагов, чем символов, честный разбор
    # сделать не может, а достижение потолка есть третий исход с причиной.
    ceiling = len(text) + 1 if max_steps is None else max_steps
    out: List[str] = []
    i = start
    steps = 0
    while i < len(text):
        steps += 1
        if steps > ceiling:
            return None, (f'разбор `PROMPT="…"` не продвигается: {steps} шагов при '
                          f'потолке {ceiling} — тело промпта НЕ ИЗМЕРЕНО')
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            # Продолжение строки оболочки текстом промпта НЕ является.
            if nxt == "\n":
                i += 2
                continue
            out.append(nxt)
            i += 2
            continue
        if ch == '"':
            return "".join(out), None
        out.append(ch)
        i += 1
    return None, 'присваивание `PROMPT="…"` не закрыто кавычкой'


def measure_instruction_doors(repo_root: Path, *,
                              max_steps: Optional[int] = None) -> Dict[str, Any]:
    """Ось D: называет ли ИНСТРУКЦИЯ дверь, которая оставляет квитанцию.

    Отвечает на вопрос «НАЗВАНА ли дверь литералом в тексте», а НЕ «предписана
    ли она»: намерения прозы прибор не меряет и не притворяется, что меряет.
    Для заказа этого довольно — он спрашивает, ЧЬЁ это свойство, и разница
    между «сессии не спрашивают сторожа» и «инструкция его не называет» видна
    уже на наличии литерала.

    Третий исход у каждой поверхности свой: файл не прочитан · присваивания
    промпта в нём нет · оно не закрыто. Любой из них — ``measured=False`` у
    поверхности и у оси целиком: «инструкция называет дверь» без одной из двух
    поверхностей НЕ ИЗМЕРЕНО, а не «названа».
    """
    # Форма записи о поверхности ПОСТОЯННА: «не вычислено» представлено `None`,
    # а не отсутствием ключа (инв. #17) — иначе читатель не отличит «поверхность
    # не прочитана» от «производитель перестал писать это поле».
    def _unmeasured(rel: str, how: str, reason: str) -> Dict[str, Any]:
        return {"path": rel, "read": how, "measured": False, "reason": reason,
                "verdict": None, "names_guard_claim": None, "names_writer": None,
                "names_guard_check_readonly": None, "chars": None}

    surfaces: Dict[str, Any] = {}
    for name, rel, how in _INSTRUCTION_SURFACES:
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            surfaces[name] = _unmeasured(rel, how,
                                         f"не прочитан: {type(exc).__name__}: {exc}")
            continue
        if how == "prompt":
            body, reason = _prompt_body(text, max_steps=max_steps)
            if body is None:
                # Причина передаётся КАК ЕСТЬ. Подстановка по умолчанию
                # (`reason or "…"`) была бы ровно тем, что инвариант #17
                # запрещает: неназванная причина обязана остаться `None`, а не
                # притвориться текстом, которого никто не измерял.
                surfaces[name] = _unmeasured(rel, how, reason)
                continue
            text = body
        names = {door: (token in text) for door, token in _DOOR_TOKENS.items()}
        if names[DOOR_GUARD] and names[DOOR_WRITER]:
            verdict = "names_both"
        elif names[DOOR_GUARD]:
            verdict = "names_guard_claim_only"
        elif names[DOOR_WRITER]:
            verdict = "names_writer_only"
        else:
            verdict = "names_neither"
        surfaces[name] = {"path": rel, "read": how, "measured": True, "reason": None,
                          "verdict": verdict,
                          "names_guard_claim": names[DOOR_GUARD],
                          "names_writer": names[DOOR_WRITER],
                          "names_guard_check_readonly": _GUARD_CHECK_TOKEN in text,
                          "chars": len(text)}
    measured = sum(1 for s in surfaces.values() if s["measured"])
    return {
        "measured": measured == len(_INSTRUCTION_SURFACES) and bool(surfaces),
        "reason": (None if measured == len(_INSTRUCTION_SURFACES) and surfaces else
                   f"прочитано {measured} из {len(_INSTRUCTION_SURFACES)} поверхностей "
                   f"инструкции — «инструкция называет дверь» НЕ ИЗМЕРЕНО целиком"),
        "surfaces": surfaces,
        "surfaces_declared": len(_INSTRUCTION_SURFACES),
        "measures": ("НАЗВАНА ли дверь литералом в тексте, а НЕ предписана ли она: "
                     "намерение прозы не меряется. И прибор НЕ судит, доходит ли "
                     "поверхность до сессии: у промпта это верно по построению (его "
                     "текст и есть вход цикла), у документа — нет"),
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
               window_days: int = _WINDOW_DAYS,
               history_root: Optional[Path] = None) -> Dict[str, Any]:
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
        # Оси C и D объявлены ОТДЕЛЬНО от `receipts` намеренно: ось B отвечает
        # ОДНИМ числом «без квитанции», а это число меряет ДВЕРЬ, не вопрос
        # (заказ G110 п. 2). Сложить их в одно поле значило бы вернуть ту самую
        # склейку, ради разведения которой заказ и поставлен.
        "doors": None,
        "instruction_doors": None,
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

    # Историю удалений спрашиваем у ПОЛНОГО клона, если он назван: рабочее
    # дерево прода обрезано по построению (замер #751 — 443 коммита при 20
    # точках обрезки), и у него на вопрос «списана или потеряна» ответа нет.
    price = measure_price(journal["records"], base,
                          retirement=retirement_door(history_root or repo_root, base["ref"]))
    if price["coordinates_declared"] == 0:
        # Слепой проход (приставка не распознана ни у одной записи) выглядел бы
        # как «дважды сделанной работы нет». Это НЕ ИЗМЕРЕНО, и громко.
        report["reason"] = ("ни одна объявленная координата не приведена к пути "
                            "репозитория — приставка деревьев не распознана")
        report["price"] = price
        return report
    receipts = measure_receipts(journal["records"], now=now, window_days=window_days)
    doors = measure_taking_doors(journal["records"], receipts=receipts, now=now,
                                 window_days=window_days)
    instruction = measure_instruction_doors(repo_root)
    wiring = measure_guard_wiring(repo_root)
    report["price"] = price
    report["receipts"] = receipts
    report["doors"] = doors
    report["instruction_doors"] = instruction
    report["guard_wiring"] = wiring

    if receipts["window_takings"] == 0:
        # Вырожденный проход: окно пусто ⇒ «у всех взятий есть квитанция»
        # верно ПО ПОСТРОЕНИЮ и ответом не является.
        report["reason"] = (f"в окне {window_days} дн. ни одного взятия предмета — "
                            "проводка не измерена, а не исправна")
        return report

    report["measured"] = True
    # Fail-CLOSED по третьему исходу двери списания: координата, про которую
    # «удаляли или нет» НЕ ИЗМЕРЕНО, не имеет права закрывать класс. Иначе
    # поверхностный клон — то есть самое обычное окружение CI — обнулил бы и
    # цену, и вердикт разом, и это читалось бы как «чисто» (урок pyflakes в
    # `.claude/rules/deployment.md`: отсутствие инструмента тише красного).
    report["status"] = (STATUS_OPEN
                        if receipts["window_takings_without_receipt"] > 0
                           or price["lost_coordinates"] > 0
                           or price["retirement_unmeasured"] > 0
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
    if not price.get("retirement_door_asked"):
        lines.append("[СПИСАНИЕ · НЕ СПРОШЕНО] дверь удаления не передана — цена ЗАВЫШЕНА "
                     "на доставленные списания; боевой путь дверь передаёт всегда")
    elif price.get("retirement_unmeasured"):
        lines.append(f"[СПИСАНИЕ · НЕ ИЗМЕРЕНО] у {price['retirement_unmeasured']} координат(ы) "
                     "история удалений не прочитана: «потеряно» и «списано» НЕ РАЗВЕДЕНЫ, "
                     "и это не «чисто»")
    if price.get("retired_at_base"):
        lines.append(f"[СПИСАНИЕ · ДОСТАВЛЕНО] {price['retired_at_base']} координат(ы) "
                     "отсутствуют на базе ПОТОМУ, что их удаление доехало — в цену не идут")
    if price.get("liftability"):
        lines.append("[ПОДЪЁМНОСТЬ потерянного] " + " · ".join(
            f"{k} {v}" for k, v in price["liftability"].items())
            + " — окно подъёма равно времени жизни дерева, а не сроку заказа")
    lines.append(
        f"[ОСЬ B] взятий предмета за {receipts['window_days']} дн. "
        f"{receipts['window_takings']}, БЕЗ квитанции сторожа "
        f"{receipts['window_takings_without_receipt']}; квитанций в журнале всего "
        f"{receipts['receipts_in_journal']}")
    lines.append(f"[ОСЬ B] {receipts['absence_means']}")
    doors = report.get("doors") or {}
    if not doors.get("measured"):
        lines.append(f"[ОСЬ C] дверь взятия НЕ ИЗМЕРЕНА — {doors.get('reason')}")
    else:
        by = doors["by_door"]
        lines.append(
            f"[ОСЬ C] ДВА числа вместо одного (заказ G110 п. 2): из "
            f"{doors['window_takings']} взятий за {doors['window_days']} дн. дверью "
            f"СТОРОЖА объявлено {doors['through_guard_door']} "
            f"({doors['through_guard_door_pct']} %), ПИСАТЕЛЕМ напрямую "
            f"{doors['by_writer_door_only']}; только сторож {by['guard_only']} · "
            f"обе {by['both']} · только писатель {by['writer_only']}")
        lines.append(f"[ОСЬ C] {doors['measures']}")
        if doors.get("takings_without_measured_identity") or doors.get("timestamps_unparsed"):
            lines.append(
                f"[ОСЬ C · ДВЕРЬ НЕ ПРИПИСАНА] взятий предмета без измеренной личности "
                f"{doors['takings_without_measured_identity']} · метка времени не "
                f"разобрана у {doors['timestamps_unparsed']} — дверь у них НЕ ИЗМЕРЕНА, "
                f"а не «писательская»; записей без предмета вовсе "
                f"{doors['records_without_subject']} (взятием предмета не являются по "
                f"построению и в знаменатель не идут)")
    instruction = report.get("instruction_doors") or {}
    if not instruction.get("measured"):
        lines.append(f"[ОСЬ D] инструкция НЕ ИЗМЕРЕНА целиком — {instruction.get('reason')}")
    for sname, surface in sorted((instruction.get("surfaces") or {}).items()):
        if not surface.get("measured"):
            lines.append(f"[ОСЬ D] {sname} ({surface['path']}): НЕ ИЗМЕРЕНО — "
                         f"{surface.get('reason')}")
            continue
        lines.append(
            f"[ОСЬ D] {sname} ({surface['path']}, {surface['read']}): "
            f"{surface['verdict']} — дверь-квитанция `claim` "
            f"{'названа' if surface['names_guard_claim'] else 'НЕ НАЗВАНА'}, "
            f"писатель {'назван' if surface['names_writer'] else 'НЕ НАЗВАН'}, "
            f"read-only `check` "
            f"{'назван' if surface['names_guard_check_readonly'] else 'не назван'}")
    if instruction.get("measures"):
        lines.append(f"[ОСЬ D] {instruction['measures']}")
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
                     + (f" · родня {finding['kin'][0]}" if finding["kin"] else "")
                     + (f" · {finding['retirement']}" if finding.get("retirement") else "")
                     + (f" · подъём: {finding['liftable']}" if finding.get("liftable") else ""))
    lines.append("НЕ ДОКЛАДЫВАЕТ: полноту добровольного журнала · были ли две сессии "
                 "передачей или переделкой · верность самого сторожа захвата · "
                 "доставку под СОВСЕМ другим именем (родня ищется в том же каталоге) · "
                 "содержимое целого дерева — подъёмность есть наличие дерева, а не работы в нём")
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
    ap.add_argument("--history-root", default=None,
                    help=("корень ПОЛНОГО клона для вопроса «координату списали или "
                          "потеряли» (по умолчанию — своё дерево; обрезанное на этот "
                          "вопрос честно отвечает «НЕ ИЗМЕРЕНО»)"))
    ap.add_argument("--base-ref", default=DEFAULT_BASE_REF, help="базовый ref доставки")
    ap.add_argument("--window-days", type=int, default=_WINDOW_DAYS)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать {ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    data_dir = Path(args.data_dir) if args.data_dir else (repo_root / "data")
    report = run_census(data_dir, repo_root=repo_root, base_ref=args.base_ref,
                        window_days=args.window_days,
                        history_root=Path(args.history_root) if args.history_root else None)
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
