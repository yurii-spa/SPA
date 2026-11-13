#!/usr/bin/env python3
"""ЗАМЕР населения класса «шаг 0a не отличает НЕЗАКОНЧЕННУЮ работу от недоставленной».

Карточка `inbox-shag-0a-ne-otlichaet-nezakonchennuyu-rab`, заказ G900 п. 1.

Шаг 0a (``scripts/check_undelivered_work.py``) отвечает на вопрос «доставлено ли
ОБЪЯВЛЕННОЕ» и называет находку словами «надо поднять». У мёртвой сессии при этом ДВА
разных состояния, и шаг 0a их не различает:

* работа ЗАКОНЧЕНА и не доставлена — поднять значит перенести байты и запушить;
* работа НЕ ЗАКОНЧЕНА — переносить нечего, потому что центрального артефакта не
  существует, и «поднять» означает ДОДЕЛАТЬ.

Замер цикла #1022: три цикла подряд (#1019/#1020/#1021) объявили ОДНУ работу по заказу
G899 и умерли; все три раза шаг 0a сказал «надо поднять», и все три раза работа была
НЕЗАКОНЧЕННОЙ — объявленного `spa_core/tests/tree_content_class_baseline.json` не было
ни в одном из пяти их деревьев.

Прибор ТОЛЬКО ЧИТАЕТ: журнал объявлений, рабочие деревья на диске и историю имён у
полного клона. Он ничего не чинит, никого не поднимает и шаг 0a не трогает.

## Две оси, и они мерят РАЗНОЕ

**Ось 1 — «объявлено, но НЕ СОЗДАНО».** Сильный признак из карточки: объявленный путь,
которого нет в дереве объявившего. Одного отсутствия МАЛО: удаление файла — тоже
доставка (цикл #297 снял корневой ``__init__.py``, и это верное действие). Поэтому
у отсутствующего пути спрашивается ВТОРОЙ вопрос — существовало ли это ИМЯ хоть раз в
истории базы. Имя, которого в истории не было НИКОГДА, не могло быть удалено: его не
создавали. Только такая пара и есть член класса.

**Ось 2 — «артефакт замера живёт ВНЕ дерева».** Вторая половина той же находки: вывод
дифференциального прогона #1020 (437 КБ) лежал в `/private/tmp/c1020_diff_base.log`, то
есть вне всякого рабочего дерева, и дал объявление класса даром — свой прогон стоил бы
циклу 97 минут. Шаг 0a мерит ПУТИ ОБЪЯВЛЕНИЯ, поэтому такой артефакт для него не
существует вовсе.

## Три исхода различимы у КАЖДОГО вопроса (инв. #17)

Ось 1 без полной истории имён не мерится ВООБЩЕ, а не «мерится приблизительно»: рабочее
дерево прода обрезано по построению (замер 03.11: 103 коммита против 27 864 у зеркала),
и «имени в истории нет» там истинно почти для любого пути. Полный клон спрашивается
ЕДИНСТВЕННОЙ существующей дверью — ``spa_core.monitoring.history_door_price
.resolve_history_root`` (ADR-688, объявление `architecture/history_roots.json`). Дверь
непригодна ⇒ ось 1 отвечает ``unmeasured`` с названной причиной и код возврата 2; своей
копии разбора объявления здесь НЕТ намеренно.

Снятое дерево объявившего — тоже ``unmeasured`` поимённо, а не «файла нет»: байтов нет
ни в дереве, ни в архиве, и выдать это за «не создавали» значило бы ровно ту подстановку,
против которой написан инв. #17.

## Чего прибор НЕ меряет (названо вслух)

* **«Законченность» по прозе объявления.** Запрещено карточкой: «объявление звучит как
  готовое» признаком не является. Прибор судит ТОЛЬКО существование файлов.
* **Историю через слияния.** ``git log --name-only`` на merge-коммите молчит по
  умолчанию; пуши идут в origin через API одиночными коммитами, поэтому цена этого
  сужения мала, но она НЕ НОЛЬ и здесь названа.
* **Чья работа.** Прибор называет СЕССИЮ объявления, а не автора: рабочее дерево не
  подписано, и атрибуцию шаг 0a тоже не выдумывает.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:  # прибор зовут и как скрипт, и импортом
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_LOG_REL = "data/session_changes.jsonl"
DEFAULT_BASE_REF = "origin/main"
# Окно, внутри которого объявление НЕ судится: работа может идти прямо сейчас, и
# «файла ещё нет» у живой сессии — нормальный ход, а не находка. То же окно и та же
# причина, что у шага 0a (`DEFAULT_GRACE_HOURS`).
DEFAULT_GRACE_HOURS = 3.0

# ── вердикты оси 1 ───────────────────────────────────────────────────────────
PRESENT = "present"
DECLARED_NEVER_CREATED = "declared_never_created"
ABSENT_KNOWN_NAME = "absent_known_name"
FRESH = "fresh"
UNMEASURED_TREE_GONE = "unmeasured_tree_gone"
UNMEASURED_ROOT = "unmeasured_root"

AXIS1_UNMEASURED = (UNMEASURED_TREE_GONE, UNMEASURED_ROOT)

# ── вердикты оси 2 ───────────────────────────────────────────────────────────
INSIDE_TREE = "inside_tree"
OUTSIDE_EXISTS = "outside_exists"
OUTSIDE_GONE = "outside_gone"

# Артефакт замера опознаётся расширением, а не словом в тексте: «похоже на отчёт» —
# та же догадка по прозе, что запрещена у оси 1.
ARTIFACT_SUFFIXES = (".log", ".json", ".jsonl", ".txt", ".xml", ".csv", ".md")

# Токен пути в свободном тексте объявления. Хвостовая пунктуация отрезается отдельно:
# в прозе путь почти всегда стоит перед запятой, точкой или закрывающей скобкой.
_PATH_TOKEN = re.compile(r"(?:/private)?/(?:tmp|var/folders)/[^\s,;)'\"»`]+")
_TRAILING = ".,;:)»'\"`"


# ───────────────────────────── чтение журнала ────────────────────────────────

def read_journal(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Записи журнала объявлений + НАЗВАННЫЕ причины у строк, которые не разобрались.

    Нечитаемая строка не выбрасывается молча: «строк 3306, разобрано 3300» и
    «разобрано 3306» — разные утверждения, и второе было бы ложным.
    """
    rows: List[Dict[str, Any]] = []
    broken: List[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — третий исход, а не пустой журнал
        return [], [f"журнал не прочитан: {type(exc).__name__}: {exc}"]
    for lineno, raw in enumerate(text.splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            broken.append(f"строка {lineno}: {type(exc).__name__}: {exc}")
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            broken.append(f"строка {lineno}: запись не объект, а {type(row).__name__}")
    return rows, broken


def parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


# ──────────────────────── дерево, назвавшее путь ─────────────────────────────

def resolve_tree_root(path: str, *,
                      exists: Callable[[Path], bool] = Path.exists,
                      cwd: Optional[str] = None,
                      ) -> Tuple[Optional[Path], str]:
    """Корень рабочего дерева, которому принадлежит ОБЪЯВЛЕННЫЙ абсолютный путь.

    Признак корня — наличие `.git` (каталог у клона, файл у линкованного worktree), а
    НЕ регистрация в `git worktree list`: снятая регистрация оставляет каталог на диске,
    и дерево, о котором мы спрашиваем, чаще всего уже не зарегистрировано.

    Три исхода: корень НАЗВАН · корень не определяется (путь относительный — дерево
    назвать нечем) · дерева на диске нет вовсе. Последние два РАЗНЫЕ: первый про форму
    объявления, второй про уборку.
    """
    raw = Path(path)
    if not raw.is_absolute():
        # Относительный путь сам дерева не называет. Назвать его может ТОЛЬКО поле
        # `cwd` той же записи — догадка по соседним путям записи была бы ровно тем
        # угадыванием, которое карточка запрещает.
        if not cwd:
            return None, "путь объявлен относительным, и `cwd` в записи нет — дерево назвать нечем"
        raw = Path(cwd) / raw
    for parent in raw.parents:
        if exists(parent / ".git"):
            return parent, f"корень по признаку .git: {parent}"
    # Корня нет. Отличаем «дерево снято» от «такого дерева не было никогда» по тому,
    # существует ли хоть один предок ниже системного каталога.
    deepest = next((p for p in raw.parents if exists(p)), None)
    if deepest is None:
        return None, "ни один предок объявленного пути не существует"
    return None, f"рабочего дерева над путём нет: самый глубокий существующий предок {deepest}"


def _resolved(path: str, *, cwd: Optional[str]) -> Path:
    """Тот же путь, что судит `resolve_tree_root`: одна дверь — одно разрешение."""
    raw = Path(path)
    if not raw.is_absolute() and cwd:
        raw = Path(cwd) / raw
    return raw


# ─────────────────────── история имён у полного клона ────────────────────────

def _run_git(root: Path, args: Sequence[str]) -> Tuple[int, str, str]:
    proc = subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def history_first_seen(root: Path, *, base_ref: str = DEFAULT_BASE_REF,
                       git: Optional[Callable[[Path, Sequence[str]], Tuple[int, str, str]]] = None,
                       ) -> Tuple[Optional[Dict[str, datetime]], str]:
    """Имя в истории базы → САМОЕ РАННЕЕ его появление, и чем это добыто.

    Нужна не принадлежность имени истории, а МОМЕНТ: вопрос «существовал ли этот файл»
    задаётся не сегодняшнему дереву, а дню объявления. Имя, появившееся на базе ПОЗЖЕ
    объявления, на момент объявления не существовало — и ровно этой формы предмет
    замера #1022: `spa_core/tests/tree_content_class_baseline.json` сегодня на базе ЕСТЬ
    (его довёз четвёртый цикл), а у трёх умерших сессий его не было. Спросить сегодняшнюю
    базу значило бы объявить тот случай «удалением», то есть потерять сам предмет.

    Возврат ``None`` означает НЕ ИЗМЕРЕНО с названной причиной, а НЕ «имён нет»: пустой
    словарь превратил бы любой отсутствующий путь в «не создавали».
    """
    runner = git or _run_git
    code, out, err = runner(root, ["log", base_ref, "--name-only", "--pretty=format:@%cI"])
    if code != 0:
        return None, (f"история {base_ref} в {root} не прочитана: git вышел {code}: "
                      f"{(err or out).strip()[:200]}")
    first: Dict[str, datetime] = {}
    stamp: Optional[datetime] = None
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("@"):
            stamp = parse_ts(line[1:])
            continue
        if stamp is not None:
            # `git log` идёт от новых к старым, поэтому последняя запись по имени и есть
            # САМАЯ РАННЯЯ: перезапись здесь не потеря, а выбор минимума одним проходом.
            first[line] = stamp
    if not first:
        return None, f"история {base_ref} в {root} не назвала ни одного имени"
    return first, f"{len(first)} имён из истории {base_ref} в {root}"


def resolve_history_door(repo_root: Path, *, base_ref: str = DEFAULT_BASE_REF,
                         resolver: Optional[Callable[..., Dict[str, Any]]] = None,
                         ) -> Tuple[Optional[Path], str]:
    """Полный клон, у которого спрашивается история имён — ЕДИНСТВЕННОЙ дверью.

    Своя копия разбора `architecture/history_roots.json` здесь означала бы, что прибор
    и ступень моста спрашивают РАЗНЫЕ клоны под одним именем «полная история».
    """
    if resolver is None:
        try:
            from spa_core.monitoring.history_door_price import (  # noqa: PLC0415
                resolve_history_root as resolver)
        except Exception as exc:  # noqa: BLE001 — третий исход
            return None, (f"дверь истории не импортируется: "
                          f"{type(exc).__name__}: {exc}")
    try:
        verdict = resolver(repo_root, base_ref=base_ref)
    except Exception as exc:  # noqa: BLE001
        return None, f"дверь истории отказала: {type(exc).__name__}: {exc}"
    root = verdict.get("root")
    if root is None:
        trail = "; ".join(str(p.get("reason") or p.get("state") or "?")
                          for p in (verdict.get("trail") or []))
        return None, f"пригодного полного клона нет ({trail or 'причина не названа'})"
    return Path(root), f"{verdict.get('named_by') or 'дверь не назвала себя'}"


# ───────────────────────────── ось 1 ─────────────────────────────────────────

def classify_declared_path(path: str, *, announced: Optional[datetime],
                           now: datetime, grace_hours: float,
                           first_seen: Dict[str, datetime],
                           exists: Callable[[Path], bool] = Path.exists,
                           cwd: Optional[str] = None,
                           ) -> Tuple[str, str]:
    """Вердикт одному объявленному пути.

    Порядок вопросов существен: сперва «можно ли вообще судить» (окно, дерево), потом
    «есть ли файл», и только у отсутствующего — «а существовало ли это имя НА МОМЕНТ
    ОБЪЯВЛЕНИЯ». Последний вопрос задаётся дню объявления, а не сегодняшнему дню:
    сегодняшняя база уже несёт то, что довёз следующий цикл.
    """
    if announced is None:
        return UNMEASURED_ROOT, "у записи нет разбираемой отметки времени"
    if now - announced < timedelta(hours=grace_hours):
        return FRESH, (f"объявлено {(now - announced).total_seconds() / 3600:.2f}ч назад "
                       f"при окне {grace_hours:.1f}ч — работа может идти")
    root, why = resolve_tree_root(path, exists=exists, cwd=cwd)
    if root is None:
        state = UNMEASURED_TREE_GONE if ("дерева" in why or "предок" in why) else UNMEASURED_ROOT
        return state, why
    target = _resolved(path, cwd=cwd)
    if exists(target):
        return PRESENT, f"файл есть в дереве {root}"
    if not exists(target.parent):
        # Каталога пути не существует. Это НЕ «файл не создавали»: так выглядит снятое
        # ВЛОЖЕННОЕ дерево (`<прод>/.claude/worktrees/<сессия>/…`), у которого поиск
        # корня по `.git` доходит до прод-дерева и начинает судить чужой путь его
        # историей. Замер 03.11: без этого вопроса такая форма дала 12 ложных членов.
        return UNMEASURED_TREE_GONE, (
            f"каталога {target.parent} не существует — он снят вместе с деревом "
            f"объявившего, а найденный корень {root} этому пути не принадлежит")
    try:
        rel = target.relative_to(root).as_posix()
    except ValueError:
        return UNMEASURED_ROOT, f"путь {target} не лежит под найденным корнем {root}"
    seen = first_seen.get(rel)
    if seen is None:
        return DECLARED_NEVER_CREATED, (f"файла в дереве {root} нет, и имени {rel} в "
                                        f"истории базы не было НИКОГДА — его не создавали")
    if seen > announced:
        return DECLARED_NEVER_CREATED, (
            f"файла в дереве {root} нет, а имя {rel} появилось на базе "
            f"{seen.strftime('%Y-%m-%dT%H:%M:%SZ')} — ПОЗЖЕ объявления "
            f"{announced.strftime('%Y-%m-%dT%H:%M:%SZ')}: на момент объявления его не было")
    return ABSENT_KNOWN_NAME, (
        f"файла в дереве нет, НО имя {rel} было на базе уже "
        f"{seen.strftime('%Y-%m-%dT%H:%M:%SZ')} — удаление это тоже доставка")


def tree_kind(root: Path, *, long_lived: Sequence[Path]) -> str:
    """Одноразовое дерево сессии или ДОЛГОЖИВУЩЕЕ (прод-дерево, зеркало).

    Деление не косметика, а СИЛА признака. Одноразовый worktree после смерти сессии не
    трогает никто — отсутствие файла там означает «его не создавали». Прод-дерево живёт
    месяцами, и файл из него мог убрать кто угодно позже, поэтому та же форма там есть
    КАНДИДАТ, а не член класса. Сложить две группы в одно число значило бы выдать
    слабый признак за сильный.
    """
    resolved = root.resolve() if root.exists() else root
    for known in long_lived:
        try:
            if resolved == known.resolve():
                return "long_lived"
        except OSError:
            continue
    return "disposable"


def census_axis_one(records: Sequence[Dict[str, Any]], *, now: datetime,
                    first_seen: Optional[Dict[str, datetime]],
                    grace_hours: float = DEFAULT_GRACE_HOURS,
                    exists: Callable[[Path], bool] = Path.exists,
                    long_lived: Sequence[Path] = (),
                    ) -> Dict[str, Any]:
    """Население оси 1 плюс ВТОРОЙ признак карточки — передача работы по одной карточке."""
    if first_seen is None:
        return {"verdict": "unmeasured",
                "reason": "история имён базы не измерена — ось 1 не мерится вовсе",
                "counts": {}, "members": [], "handoffs": [],
                "cards_with_many_sessions": None}

    counts: Dict[str, int] = {}
    members: List[Dict[str, Any]] = []
    # card -> session -> {state -> [rel paths]}
    by_card: Dict[str, List[Dict[str, Any]]] = {}

    for row in records:
        announced = parse_ts(row.get("ts"))
        session = str(row.get("session") or "?")
        card = (row.get("card") or "").strip()
        card_key = Path(card).name if card else ""
        cwd = (row.get("cwd") or "").strip() or None
        seen: List[Tuple[str, str, str]] = []
        for raw in row.get("files") or []:
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = raw.strip()
            state, detail = classify_declared_path(
                path, announced=announced, now=now, grace_hours=grace_hours,
                first_seen=first_seen, exists=exists, cwd=cwd)
            counts[state] = counts.get(state, 0) + 1
            seen.append((state, path, detail))
            if state == DECLARED_NEVER_CREATED:
                root, _why = resolve_tree_root(path, exists=exists, cwd=cwd)
                kind = tree_kind(root, long_lived=long_lived) if root else "unknown"
                members.append({"session": session, "ts": row.get("ts"),
                                "path": path, "card": card_key, "detail": detail,
                                "tree": str(root) if root else None, "tree_kind": kind,
                                "summary": (row.get("summary") or "")[:160]})
        if card_key:
            by_card.setdefault(card_key, []).append(
                {"session": session, "ts": row.get("ts"), "paths": seen})

    handoffs = _handoffs(by_card)
    judged = sum(v for k, v in counts.items()
                 if k in (PRESENT, DECLARED_NEVER_CREATED, ABSENT_KNOWN_NAME))
    unmeasured = sum(v for k, v in counts.items() if k in AXIS1_UNMEASURED)
    strong = [m for m in members if m["tree_kind"] == "disposable"]
    return {"verdict": "measured", "counts": counts, "members": members,
            "handoffs": handoffs,
            "members_disposable_tree": len(strong),
            "members_long_lived_tree": len(members) - len(strong),
            "judged_paths": judged, "unmeasured_paths": unmeasured,
            "cards_with_many_sessions": sum(
                1 for rows in by_card.values()
                if len({r["session"] for r in rows}) >= 2)}


# Хвост пути ОТ КОРНЯ дерева: сравнивать базовые имена значило бы считать передачей
# работы совпадение `STATE.md` в двух разных деревьях, а сравнивать полные пути —
# никогда не находить передачу вовсе (у каждой сессии своё дерево).
_REPO_DIRS = ("spa_core/", "scripts/", "tests/", "docs/", "nimbalyst-local/",
              "landing/", "architecture/", "research/", "studio_shell/", "data/")


def _repo_relative(path: str) -> str:
    posix = Path(path).as_posix()
    for marker in _REPO_DIRS:
        idx = posix.find("/" + marker)
        if idx >= 0:
            return posix[idx + 1:]
    return Path(path).name


def _handoffs(by_card: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """ВТОРОЙ признак карточки: один путь — у ранней сессии не создан, у поздней есть.

    Это и есть «работу ДОДЕЛАЛИ, а не довезли», выраженное наблюдением, а не прозой.
    """
    out: List[Dict[str, Any]] = []
    for card, rows in sorted(by_card.items()):
        ordered = sorted(rows, key=lambda r: r["ts"] or "")
        sessions = [r["session"] for r in ordered]
        if len(set(sessions)) < 2:
            continue
        # rel-имя → (первая сессия, объявившая его НЕ СОЗДАННЫМ)
        missing: Dict[str, str] = {}
        finished: Dict[str, str] = {}
        for row in ordered:
            for state, path, _why in row["paths"]:
                name = _repo_relative(path)
                if state == DECLARED_NEVER_CREATED:
                    missing.setdefault(name, row["session"])
                elif state == PRESENT and name in missing and name not in finished:
                    if row["session"] != missing[name]:
                        finished[name] = row["session"]
        if finished:
            out.append({"card": card,
                        "sessions": len(set(sessions)),
                        "sessions_sample": sorted(set(sessions))[:6],
                        "completed_later": [
                            {"artifact": name,
                             "declared_missing_by": missing[name],
                             "created_by": session}
                            for name, session in sorted(finished.items())]})
    return out


# ───────────────────────────── ось 2 ─────────────────────────────────────────

def mentioned_paths(text: str) -> List[str]:
    """Пути-кандидаты, названные в свободном тексте объявления."""
    out: List[str] = []
    for hit in _PATH_TOKEN.findall(text or ""):
        token = hit.rstrip(_TRAILING)
        if token and token not in out:
            out.append(token)
    return out


# Каталоги, где живут артефакты замера мёртвых сессий. Список НАЗВАН, а не найден
# обходом всего диска: обход `/` отвечал бы на вопрос «что вообще лежит на машине».
ARTIFACT_DIRS = ("/tmp", "/private/tmp")
ARTIFACT_SCAN_DEPTH = 2


def supply_on_disk(dirs: Sequence[str] = ARTIFACT_DIRS, *,
                   depth: int = ARTIFACT_SCAN_DEPTH,
                   lister: Optional[Callable[[Path], Iterable[Path]]] = None,
                   is_tree: Optional[Callable[[Path], bool]] = None,
                   ) -> Tuple[List[Path], List[str]]:
    """ПРЕДЛОЖЕНИЕ: артефакты, лежащие ВНЕ всякого рабочего дерева, и причины пропусков.

    Это первая половина оси 2 и она НЕ ЗАВИСИТ от записи: вопрос «сколько таких
    артефактов вообще есть» и вопрос «сколько из них названо» — разные, и ответ на
    второй без первого не значит ничего (знакомая форма: зелёный ответ своему вопросу).
    """
    found: List[Path] = []
    skipped: List[str] = []
    walker = lister or (lambda d: d.iterdir())
    tree_probe = is_tree or (lambda d: (d / ".git").exists())

    def _walk(directory: Path, level: int) -> None:
        try:
            entries = list(walker(directory))
        except Exception as exc:  # noqa: BLE001 — пропуск НАЗЫВАЕТСЯ, а не молчит
            skipped.append(f"{directory}: {type(exc).__name__}: {exc}")
            return
        for entry in entries:
            try:
                if entry.is_dir():
                    if tree_probe(entry):
                        continue  # внутри рабочего дерева — не наша ось
                    if level < depth:
                        _walk(entry, level + 1)
                elif entry.suffix.lower() in ARTIFACT_SUFFIXES:
                    found.append(entry)
            except OSError as exc:
                skipped.append(f"{entry}: {type(exc).__name__}: {exc}")
    for raw in dirs:
        root = Path(raw)
        if not root.exists():
            skipped.append(f"{root}: каталога нет")
            continue
        _walk(root, 1)
    return found, skipped


def census_axis_two(records: Sequence[Dict[str, Any]], *,
                    exists: Callable[[Path], bool] = Path.exists,
                    corpus: Sequence[str] = (),
                    supply: Optional[Tuple[List[Path], List[str]]] = None,
                    ) -> Dict[str, Any]:
    """Население оси 2 — ДВУМИ половинами, и они не складываются в одно число.

    Половина «названо»: путь вне дерева, названный в объявлении или в тексте карточки.
    Половина «предложение»: такой же артефакт, лежащий на диске, — названный он или нет.
    Доля второго в первом и есть ответ на вопрос карточки «пригодился бы поднимающему»:
    артефакт, которого запись не называет, для поднимающего НЕ СУЩЕСТВУЕТ.
    """
    counts: Dict[str, int] = {}
    members: List[Dict[str, Any]] = []
    named: set = set()
    for row in records:
        text = " ".join(str(row.get(k) or "") for k in ("summary", "verified"))
        for token in mentioned_paths(text):
            root, _why = resolve_tree_root(token, exists=exists)
            if root is not None:
                state = INSIDE_TREE
            elif exists(Path(token)):
                state = OUTSIDE_EXISTS
            else:
                state = OUTSIDE_GONE
            counts[state] = counts.get(state, 0) + 1
            if state == OUTSIDE_EXISTS and Path(token).suffix.lower() in ARTIFACT_SUFFIXES:
                counts["outside_artifact"] = counts.get("outside_artifact", 0) + 1
                members.append({"session": str(row.get("session") or "?"),
                                "ts": row.get("ts"), "path": token,
                                "named_in": "объявление"})
                named.add(token)

    # Вторая дверь записи — ТЕКСТ КАРТОЧЕК (карточка названа в задании прямо).
    corpus_hits: set = set()
    for text in corpus:
        for token in mentioned_paths(text):
            root, _why = resolve_tree_root(token, exists=exists)
            if root is None and exists(Path(token)) \
                    and Path(token).suffix.lower() in ARTIFACT_SUFFIXES:
                corpus_hits.add(token)
    for token in sorted(corpus_hits - named):
        members.append({"session": None, "ts": None, "path": token,
                        "named_in": "текст карточки"})
        named.add(token)
    counts["named_in_cards_only"] = len(corpus_hits - set(
        m["path"] for m in members if m["named_in"] == "объявление"))

    found, skipped = supply if supply is not None else supply_on_disk()
    supply_paths = {str(p) for p in found}
    named_of_supply = sorted(supply_paths & named)
    return {"verdict": "measured", "counts": counts, "members": members,
            "supply_on_disk": len(found),
            "supply_named_by_the_record": len(named_of_supply),
            "supply_skipped": skipped,
            "named_total": len(named)}


# ──────────────────────────────── отчёт ──────────────────────────────────────

def measure(repo_root: Path, *, log: Optional[Path] = None, now: Optional[datetime] = None,
            base_ref: str = DEFAULT_BASE_REF, grace_hours: float = DEFAULT_GRACE_HOURS,
            exists: Callable[[Path], bool] = Path.exists,
            history: Optional[Tuple[Optional[Dict[str, datetime]], str]] = None,
            tracker_dir: Optional[Path] = None,
            ) -> Dict[str, Any]:
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    log_path = log or (repo_root / DEFAULT_LOG_REL)
    records, broken = read_journal(log_path)

    door: Optional[Path] = None
    if history is None:
        door, door_why = resolve_history_door(repo_root, base_ref=base_ref)
        if door is None:
            names, names_why = None, door_why
        else:
            names, names_why = history_first_seen(door, base_ref=base_ref)
    else:
        names, names_why = history

    # Долгоживущие деревья: своё прод-дерево и объявленный полный клон. Их список
    # НАЗВАН, а не угадан по возрасту каталога — иначе сила признака зависела бы от
    # того, когда последний раз чистили `/tmp`.
    long_lived = [repo_root] + ([door] if door is not None else [])
    axis1 = census_axis_one(records, now=stamp, first_seen=names,
                            grace_hours=grace_hours, exists=exists,
                            long_lived=long_lived)
    tracker = tracker_dir or (repo_root / "nimbalyst-local" / "tracker")
    axis2 = census_axis_two(records, exists=exists, corpus=card_corpus(tracker))

    return {"schema_version": 1,
            "measured_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "journal": str(log_path), "tracker": str(tracker),
            "records": len(records),
            "unparsed_lines": broken,
            "history_names": names_why,
            "grace_hours": grace_hours,
            "axis_one": axis1, "axis_two": axis2}


def card_corpus(tracker: Path, *, limit: int = 4000) -> List[str]:
    """Тексты карточек трекера — вторая объявленная дверь записи для оси 2.

    Читается ТОЛЬКО трекер: обходить весь репозиторий значило бы считать упоминанием
    путь в чужом логе, случайно закоммиченном, и ответ стал бы свойством мусора.

    **Каталог передаётся ВХОДОМ, а не берётся от `--repo-root`.** Журнал объявлений
    живёт в прод-дереве (он runtime), а очередь карточек там РАСХОДИТСЯ с origin — замер
    #1022: 668 карточек из 1569 в прод-дереве нет вовсе. Прочитать обе двери у одного
    дерева значило бы мерить ось 2 по заведомо неполной записи: именно так первый прогон
    этого прибора не нашёл `/private/tmp/c1020_diff_base.log`, названный в ДВУХ карточках
    на `origin/main`.
    """
    out: List[str] = []
    if not tracker.is_dir():
        return out
    for path in sorted(tracker.glob("*.md"))[:limit]:
        try:
            out.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return out


def exit_code(report: Dict[str, Any]) -> int:
    """0 — измерено, класс пуст · 1 — есть находки · 2 — НЕ ИЗМЕРЕНО."""
    if report["axis_one"]["verdict"] != "measured":
        return 2
    if report["unparsed_lines"]:
        return 2
    if report["axis_one"]["members"] or report["axis_two"]["members"]:
        return 1
    return 0


def render(report: Dict[str, Any]) -> str:
    a1, a2 = report["axis_one"], report["axis_two"]
    lines = [f"ЗАМЕР класса «объявлено, но НЕ СОЗДАНО» — {report['measured_at']}",
             f"  журнал: {report['journal']} · записей {report['records']}",
             f"  карточки (вторая дверь записи): {report['tracker']}",
             f"  история имён: {report['history_names']}"]
    if report["unparsed_lines"]:
        lines.append(f"  ⚠️ НЕ ИЗМЕРЕНО — строк не разобрано: {len(report['unparsed_lines'])}")
        for why in report["unparsed_lines"][:5]:
            lines.append(f"      • {why}")
    if a1["verdict"] != "measured":
        lines.append(f"  ⚠️ ОСЬ 1 НЕ ИЗМЕРЕНА: {a1.get('reason')}")
    else:
        counts = a1["counts"]
        lines.append("  ОСЬ 1 (объявлено, но не создано): "
                     + " · ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        lines.append(f"  → ЧЛЕНОВ КЛАССА: {len(a1['members'])}"
                     f" из {a1['judged_paths']} СУДИМЫХ путей"
                     f" (НЕ ИЗМЕРЕНО {a1['unmeasured_paths']} — дерево снято либо не названо)")
        lines.append(f"  → признак СИЛЬНЫЙ (одноразовое дерево сессии): "
                     f"{a1['members_disposable_tree']} · признак СЛАБЫЙ "
                     f"(долгоживущее дерево, файл мог убрать кто угодно позже): "
                     f"{a1['members_long_lived_tree']}")
        lines.append(f"  → карточек с ≥2 сессиями: {a1['cards_with_many_sessions']}"
                     f" · передач работы (доделали, а не довезли): {len(a1['handoffs'])}")
        for row in a1["members"][:12]:
            lines.append(f"      • {row['session']} {row['ts']} {row['path']}")
        if len(a1["members"]) > 12:
            lines.append(f"      … и ещё {len(a1['members']) - 12}")
        for hand in a1["handoffs"]:
            lines.append(f"      ↳ карточка {hand['card']}: сессий {hand['sessions']}"
                         f" (напр. {', '.join(hand['sessions_sample'])})")
            for item in hand["completed_later"]:
                lines.append(f"          {item['artifact']}: объявлена отсутствующей "
                             f"{item['declared_missing_by']} → создана {item['created_by']}")
    lines.append("  ОСЬ 2 (артефакт замера ВНЕ дерева): "
                 + (" · ".join(f"{k}={v}" for k, v in sorted(a2["counts"].items()))
                    or "упоминаний пути нет"))
    lines.append(f"  → НАЗВАНО записью: {a2['named_total']}"
                 f" · ПРЕДЛОЖЕНИЕ на диске: {a2['supply_on_disk']}"
                 f" · из предложения названо: {a2['supply_named_by_the_record']}")
    if a2["supply_skipped"]:
        lines.append(f"      НЕ ИЗМЕРЕНО при обходе: {len(a2['supply_skipped'])}"
                     f" (напр. {a2['supply_skipped'][0]})")
    lines.append(f"  → ЧЛЕНОВ ОСИ 2: {len(a2['members'])}")
    for row in a2["members"][:12]:
        lines.append(f"      • {row['session']} {row['ts']} {row['path']}")
    if len(a2["members"]) > 12:
        lines.append(f"      … и ещё {len(a2['members']) - 12}")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ — ничего не поднимает и не чинит")
    return "\n".join(lines)


# ───────────────────── писатель объявления (КОД, не рука) ────────────────────

DECLARATION_REL = "spa_core/tests/unfinished_work_class_baseline.json"

CLASS = "class"            # НЕЗАКОНЧЕННАЯ работа — член класса
RENAME = "rename"          # работа доставлена под ДРУГИМ именем — ложное срабатывание
VERDICTS = (CLASS, RENAME)


class DeclarationRefused(Exception):
    """Объявление НЕ пишется: оно стало бы ложным. Причина всегда названа."""


def build_declaration(report: Dict[str, Any], *, adr: str, order: str,
                      measured_in: str, instrument: str, base_sha: str,
                      classification: Dict[str, Dict[str, str]],
                      seam: Dict[str, Any]) -> Dict[str, Any]:
    """Проекция ЗАМЕРА на объявление — с отказом на всём, что сделало бы его ложным.

    Отказы (каждый с причиной): замер не состоялся · класс пуст · не названы ADR / заказ /
    замер / прибор / sha базы · сильный член НЕ РАЗОБРАН рукой · у разбора нет
    доказательства · выбор шва не назван вместе с ценой отвергнутых.

    Разбор сильных членов — РУКА, и именно поэтому он входит ДАННЫМИ с доказательством у
    каждой строки: признак «объявлено и отсутствует» на замере 03.11 ошибается в 2 случаях
    из 5 (переименование при доставке), и объявление, не назвавшее этого, выдало бы
    ложное срабатывание за член класса.
    """
    a1, a2 = report["axis_one"], report["axis_two"]
    if a1.get("verdict") != "measured":
        raise DeclarationRefused(f"ось 1 не измерена: {a1.get('reason')}")
    if report["unparsed_lines"]:
        raise DeclarationRefused(
            f"журнал разобран НЕ ПОЛНОСТЬЮ: {len(report['unparsed_lines'])} строк")
    for name, value in (("adr", adr), ("order", order), ("measured_in", measured_in),
                        ("instrument", instrument), ("base_sha", base_sha)):
        if not str(value or "").strip():
            raise DeclarationRefused(f"не названо обязательное поле `{name}`")

    strong = [m for m in a1["members"] if m["tree_kind"] == "disposable"]
    if not strong:
        raise DeclarationRefused(
            "сильный признак не дал ни одного члена — «класс пуст» утверждается "
            "прибором, а не писателем, и пустое объявление этого не доказывает")

    rows: List[Dict[str, Any]] = []
    for member in strong:
        key = f"{member['session']}:{Path(member['path']).name}"
        verdict = classification.get(key)
        if not verdict:
            raise DeclarationRefused(
                f"сильный член {key} НЕ РАЗОБРАН: признак ошибается, и необъяснённая "
                f"строка превратила бы ложное срабатывание в член класса")
        state = str(verdict.get("verdict") or "").strip()
        evidence = str(verdict.get("evidence") or "").strip()
        if state not in VERDICTS:
            raise DeclarationRefused(f"у {key} вердикт `{state}` не из {VERDICTS}")
        if not evidence:
            raise DeclarationRefused(f"у {key} вердикт без ДОКАЗАТЕЛЬСТВА")
        rows.append({"session": member["session"], "ts": member["ts"],
                     "path": member["path"], "tree": member["tree"],
                     "card": member["card"], "verdict": state, "evidence": evidence})

    chosen = str(seam.get("chosen") or "").strip()
    if not chosen:
        raise DeclarationRefused("шов не назван — ни выбранный, ни осознанный отказ")
    if not str(seam.get("why") or "").strip():
        raise DeclarationRefused("у выбора шва нет причины")
    refused = seam.get("refused") or []
    if not refused:
        raise DeclarationRefused(
            "цена отвергнутых путей не названа — выбор без альтернатив есть жест")
    for item in refused:
        if not str(item.get("price") or "").strip():
            raise DeclarationRefused(
                f"у отвергнутого пути `{item.get('option')}` не названа ЦЕНА")

    members_of_class = [r for r in rows if r["verdict"] == CLASS]
    return {
        "schema_version": 1, "adr": adr, "order": order,
        "instrument": instrument, "measured_in": measured_in,
        "base_sha": base_sha, "measured_at": report["measured_at"],
        "journal_records": report["records"],
        "history_names": report["history_names"],
        "axis_one": {
            "members_total": len(a1["members"]),
            "strong_sign": len(strong),
            "weak_sign": a1["members_long_lived_tree"],
            "judged_paths": a1["judged_paths"],
            "unmeasured_paths": a1["unmeasured_paths"],
            "class_members": len(members_of_class),
            "sign_false_positives": len(rows) - len(members_of_class),
            "sign_precision": f"{len(members_of_class)}/{len(rows)}",
            "subjects_of_class": sorted({Path(r["path"]).name
                                         for r in members_of_class}),
            "rows": rows,
        },
        "axis_two": {
            "supply_on_disk": a2["supply_on_disk"],
            "named_by_the_record": a2["named_total"],
            "named_of_supply": a2["supply_named_by_the_record"],
            "unmeasured_while_walking": len(a2["supply_skipped"]),
        },
        "seam": {"chosen": chosen, "why": seam["why"], "refused": list(refused)},
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=str(PROJECT_ROOT),
                    help="дерево, о журнале которого спрашивается")
    ap.add_argument("--log", default=None, help="журнал объявлений (JSONL)")
    ap.add_argument("--tracker-dir", default=None,
                    help="каталог карточек (вторая дверь записи для оси 2); по умолчанию "
                         "трекер --repo-root, но прод-копия очереди расходится с origin")
    ap.add_argument("--base", default=DEFAULT_BASE_REF, help="базовый ref")
    ap.add_argument("--grace-hours", type=float, default=DEFAULT_GRACE_HOURS,
                    help="окно, внутри которого объявление не судится")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--emit-declaration", metavar="СПЕЦИФИКАЦИЯ",
                    help="записать объявление класса по спецификации (JSON: adr, order, "
                         "measured_in, base_sha, classification, seam). Писатель — КОД: "
                         "он ОТКАЗЫВАЕТ на всём, что сделало бы объявление ложным")
    ap.add_argument("--declaration-out", default=None,
                    help=f"куда писать объявление (по умолчанию <repo>/{DECLARATION_REL})")
    args = ap.parse_args(list(argv) if argv is not None else None)
    from spa_core.utils.live_paths import refuse_if_sandbox_leaks  # ADR-1000: дверь песочницы, транш 1
    refuse_if_sandbox_leaks(args.repo_root, who="unfinished_work_census")

    root = Path(args.repo_root).expanduser().resolve()
    report = measure(root, log=Path(args.log).expanduser() if args.log else None,
                     base_ref=args.base, grace_hours=args.grace_hours,
                     tracker_dir=(Path(args.tracker_dir).expanduser()
                                  if args.tracker_dir else None))
    if args.emit_declaration:
        try:
            spec = json.loads(Path(args.emit_declaration).expanduser().read_text("utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"ОТКАЗ: спецификация не прочитана: {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            return 2
        try:
            declaration = build_declaration(
                report, adr=spec.get("adr", ""), order=spec.get("order", ""),
                measured_in=spec.get("measured_in", ""),
                instrument=spec.get("instrument", "scripts/unfinished_work_census.py"),
                base_sha=spec.get("base_sha", ""),
                classification=spec.get("classification") or {},
                seam=spec.get("seam") or {})
        except DeclarationRefused as exc:
            print(f"ОТКАЗ писателя объявления: {exc}", file=sys.stderr)
            return 3
        # Умолчание — дерево САМОГО ПРИБОРА, а не `--repo-root`. Это разные деревья по
        # построению: журнал объявлений живёт в прод-дереве (он runtime), а объявление
        # класса есть КОД и уезжает из дерева доставки. Первый прогон этого писателя
        # ушёл умолчанием в прод-дерево — запись в прод-дерево принадлежит владельцу
        # (`.claude/rules/deployment.md` п. 6), и файл пришлось снимать руками.
        out = (Path(args.declaration_out).expanduser() if args.declaration_out
               else PROJECT_ROOT / DECLARATION_REL)
        out.write_text(json.dumps(declaration, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print(f"объявление записано: {out} · членов класса "
              f"{declaration['axis_one']['class_members']} · точность признака "
              f"{declaration['axis_one']['sign_precision']}")
        return exit_code(report)

    print(json.dumps(report, ensure_ascii=False, indent=1, default=str)
          if args.json else render(report))
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
