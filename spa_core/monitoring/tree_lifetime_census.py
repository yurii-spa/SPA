"""Срок годности объявления владения: чем он НАБЛЮДЁН и почему остаток не число.

**Заказ G112 п. 2 (ADR-538), дословно:**

> **Срок годности объявления владения не назван нигде.** Замер: окно подъёма равно
> времени жизни `/tmp`, а приказ «поднять» пришёл через 32 дня. Прибор обязан называть
> не только «подъёмно/нет», но и СКОЛЬКО осталось — иначе следующий заказ опоздает тем
> же способом. Мерить надо наблюдённый срок жизни одноразовых деревьев, а не выдумывать
> порог.

Усиление того же предмета — **G688 п. 4 (ADR-688)**: «померить, сколько такой работы
теряется ВПЕРЁД при нынешнем окне жизни `/tmp`, и назвать это числом рядом с пятью».

## ГЛАВНАЯ НАХОДКА: посылка заказа про `/tmp` ИЗМЕРЕННО НЕВЕРНА

Заказ назвал клок окна подъёма — «время жизни `/tmp`». На этом хосте `/tmp` не убил
НИ ОДНОГО дерева: старейшее живое рождено 2026-09-30T03:47Z и живо 260 ч, при аптайме
261 ч. Единственный наблюдённый клок, общий для всего `/tmp`, — **перезагрузка**, и она
была ОДНА (2026-09-30 00:48 местного). Поэтому «время жизни `/tmp`» — не порог, который
можно прочитать, а событие, которого на этом хосте в наблюдении нет.

**Про системную уборку сказано РОВНО то, что измерено, и это НЕ «уборки нет».** Замер
10.10 на Darwin 27: обоих файлов объявления (`/etc/defaults/periodic.conf`,
`/etc/periodic.conf`) на хосте НЕ СУЩЕСТВУЕТ — BSD-механизм `periodic` здесь отсутствует
целиком. Поэтому вердикт двери — `mechanism_absent`, а не `absent`: «порог не объявлен»
и «механизма объявления нет» различаются тем, что во втором случае прибор не знает,
отсутствует ли уборка или он смотрит не туда. Первая редакция этой шапки утверждала,
что файлы прочитаны и строки в них нет; это было НЕВЕРНО, и исправлено замером, а не
правкой формулировки.

## Остаток НЕ НАЗВАН числом, и это измерение, а не отказ

Заказ требовал назвать «сколько осталось». Прибор отвечает **третьим исходом**
(`remaining_window.measured=False`) и называет ТРИ причины, каждую ЗАМЕРОМ, а не
рассуждением:

| причина | чем измерена | замер 10.10 |
|---|---|---|
| `ceiling_is_uptime` | макс. наблюдённое выживание против аптайма | 260.3 ч против 261.4 ч |
| `no_declared_tmp_timer` | чтение объявления системной уборки | обоих файлов НЕ СУЩЕСТВУЕТ (`mechanism_absent`) |
| `reaper_excludes_the_population` | правило уборщика против населения полных наблюдений | 262 полных наблюдения, все — деревья, которые уборщик ВЗЯЛ |

Третья причина — самая важная и ровно та, которую заказ не предполагал. **Полные
наблюдения срока жизни есть только у той популяции, чья смерть безвредна.** Уборщик
(`scripts/reap_stale_worktrees.py`, ADR-230) по построению ОТКАЗЫВАЕТСЯ снимать дерево,
в котором лежит недоставленная работа: хоть один путь `unique`/`absent` — дерево
остаётся. Значит квитанции описывают деревья, уже отдавшие работу, а окно подъёма нужно
для деревьев, которые её ещё держат. Посчитать квантиль по квитанциям и выдать его за
срок годности объявления владения было бы отбором по исходу: число получилось бы
(медиана 1.8 ч, p95 68.9 ч, max 114.3 ч) и было бы про НЕ ТУ популяцию.

Выдумать порог заказ запретил прямо. Поэтому прибор называет не остаток, а ЦЕНУ его
отсутствия — следующим числом.

## Зато названо число, которого не было: ТАКТ МОЛЧАЛИВОЙ ПОТЕРИ

Из 722 известных одноразовых деревьев (население мерено ФОРМОЙ записи, см. `population`)
**438 исчезли без квитанции**. Это не описка
уборщика: у них нет ни строки в журнале квитанций, ни архива в `~/SPA_backups/
worktree_reap/` (проверено поимённо; архивов 676, квитанций 675, архив без квитанции 1,
квитанция без архива 0). 411 из 438 объявлены ДО последней загрузки, и перезагрузка их
объясняет. **Остальные 27 исчезли УЖЕ В ЭТОМ АПТАЙМЕ — их не объясняет ничто:** ни
квитанция, ни архив, ни загрузка. Протокол §3.4 ручное снятие запрещает, и 27 случаев
за 261 ч (≈2.5 дерева в сутки) — измеренная цена этого запрета, то есть ровно то
«сколько теряется ВПЕРЁД», которое просил G688 п. 4.

Направление ошибки названо: 27 — **нижняя** граница. Дерево, не объявленное журналом
вовсе, в население не попадает (на диске 67 каталогов `/tmp/spa_*`, из них журналом
названы 22), поэтому молчаливых потерь не меньше, чем 27, и сколько именно — предмет
соседа (`unannounced_divergence_scan`), а не этого прибора.

## Третий исход есть у КАЖДОГО числа (инв. #17)

Журнал не прочитан · отметка не разобрана · рождение неизвестно · объявление уборки не
читается — всё это `None`/`unmeasured` с НАЗВАННОЙ причиной, а не ноль и не успех.
Отдельно назван класс, найденный по дороге: **у журнала квитанций ДВЕ формы отметки** —
канон `2026-10-10T15:00:55Z` и сжатая `20260814T162600Z`. Канонический разбор сжатую
ОТКАЗЫВАЕТ, поэтому такие квитанции невидимы любому читателю по дате. Прибор их не
роняет молча: считает (`receipts_unparsed`) и называет. Это класс ADR-682 («у одного
поля много дверей часов») на другом файле; дверь здесь НЕ расширена — расширить её
значило бы починить вслепую то, чего заказ не просил.

## Рождение: у двух популяций РАЗНЫЕ двери, и обе объявлены

| популяция | дверь рождения | род числа |
|---|---|---|
| живое дерево | `st_birthtime` каталога | ТОЧНОЕ рождение |
| снятое/исчезнувшее дерево | первое упоминание в журнале объявлений | рождение НЕ ПОЗЖЕ этого ⇒ срок жизни есть НИЖНЯЯ граница |

Склеить их значило бы выдать нижнюю границу за замер. Поэтому выживание живого дерева
помечено `censored=True` (дерево ещё живо — возраст это нижняя граница срока жизни), а
у снятого дополнительно `birth_is_upper_bound=True`.

## ADVISORY

Прибор только ЧИТАЕТ (`applied=False`): журнал объявлений, журнал квитанций, каталоги
`/tmp`, архив уборщика, объявление системной уборки и время загрузки. Деревьев он НЕ
СНИМАЕТ, порога годности не назначает, карточек не двигает, правила уборщика не правит.
Только stdlib, сети нет. RiskPolicy v1.0, стоп-кран, аллокатор, живой трек
(`data/equity_curve_daily.json`), `landing/**` и флот не тронуты.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover — прямой запуск файла
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ARTIFACT_NAME = "tree_lifetime_census.json"
ORDER = ("G112 п. 2 (ADR-538) + G688 п. 4 (ADR-688) — срок годности объявления "
         "владения: наблюдённый срок жизни одноразовых деревьев и такт их потери")

STATUS_MEASURED = "TREE_LIFETIME_MEASURED"
STATUS_UNMEASURED = "UNMEASURED"

JOURNAL_NAME = "session_changes.jsonl"
REAP_LEDGER_NAME = "worktree_reap_log.jsonl"
REAP_ARCHIVE_DIR = "~/SPA_backups/worktree_reap"

#: Каталоги, внутри которых живут одноразовые деревья. `/private/tmp` и `/tmp` на macOS
#: — ОДИН каталог, поэтому формы сводятся к одной (см. #303 у соседа).
TMP_ROOTS = ("/tmp/", "/private/tmp/")
_TOP = re.compile(r"^(/tmp/[^/]+)")

#: Канонический разбор отметки. Сжатую форму журнала квитанций он ОТКАЗЫВАЕТ намеренно:
#: расширить дверь здесь значило бы починить вслепую класс ADR-682, которого заказ не
#: касался. Отказ обязан быть СЧИТАН, а не проглочен (`receipts_unparsed`).
_TS = "%Y-%m-%dT%H:%M:%SZ"

#: Где объявляется системная уборка `/tmp` на macOS. Читается ОБЪЯВЛЕНИЕ, а не
#: догадка о поведении: отсутствие строки — это «уборка не объявлена», а нечитаемый
#: файл — «не измерено», и это разные вердикты.
TMP_SWEEP_FILES = ("/etc/defaults/periodic.conf", "/etc/periodic.conf")
TMP_SWEEP_KEY = "daily_clean_tmps_enable"

CAUSE_ALIVE = "alive"
CAUSE_REAPED = "reaped_receipt"
CAUSE_VANISHED_BOOT = "vanished_explained_by_boot"
CAUSE_VANISHED_SILENT = "vanished_no_trace_within_uptime"

REASON_CEILING = "ceiling_is_uptime"
REASON_NO_TIMER = "no_declared_tmp_timer"
REASON_SELECTION = "reaper_excludes_the_population"


# --------------------------------------------------------------------------- чтение

def _read_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """(записи, причина-если-не-прочитано). Битые строки СЧИТАЮТСЯ, а не глотаются."""
    if not path.exists():
        return [], f"журнала нет ({path})"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], f"журнал не прочитан ({path}): {exc}"
    rows, bad = [], 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows, (f"битых строк в {path.name}: {bad}" if bad else None)


def norm_tree(path: Any) -> Optional[str]:
    """Верхний каталог внутри `/tmp` в ОДНОЙ форме, либо ``None`` — путь не в `/tmp`."""
    if not path:
        return None
    text = str(path)
    if text.startswith("/private/tmp/"):
        text = text.replace("/private/tmp/", "/tmp/", 1)
    hit = _TOP.match(text)
    return hit.group(1) if hit else None


def parse_ts(value: Any) -> Optional[datetime]:
    """Канонический разбор отметки, либо ``None``. Сжатую форму ОТКАЗЫВАЕТ (см. шапку)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, _TS).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def population(journal: Sequence[Dict[str, Any]],
               ledger: Sequence[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, str], int]:
    """(первое упоминание дерева, квитанция снятия, сколько квитанций не разобрано).

    **Население мерится ФОРМОЙ записи, а не именем пути.** Дерево — это то, что было
    `cwd` объявления, либо то, внутри чего СТРОГО лежал объявленный путь. Путь,
    встреченный только как сам объявленный файл, деревом не является: иначе
    `/tmp/c542_full.log` (лог-файл) попал бы в население деревьев и исказил и
    численность, и срок жизни. Квитанция снимается только с дерева, поэтому её путь в
    население входит всегда.
    """
    first: Dict[str, str] = {}
    is_tree: set = set()

    def _seen(tree: str, ts: Any) -> None:
        if not isinstance(ts, str):
            return
        if tree not in first or ts < first[tree]:
            first[tree] = ts

    for row in journal:
        ts = row.get("ts")
        cwd = norm_tree(row.get("cwd"))
        if cwd:                                  # cwd по построению каталог
            is_tree.add(cwd)
            _seen(cwd, ts)
        files = row.get("files")
        for item in (files if isinstance(files, list) else []):
            tree = norm_tree(item)
            if not tree:
                continue
            text = str(item)
            if text.startswith("/private/tmp/"):
                text = text.replace("/private/tmp/", "/tmp/", 1)
            if text.rstrip("/") != tree:         # лежит СТРОГО внутри ⇒ tree каталог
                is_tree.add(tree)
            _seen(tree, ts)

    death: Dict[str, str] = {}
    unparsed = 0
    for row in ledger:
        tree = norm_tree(row.get("worktree"))
        if not tree:
            continue
        is_tree.add(tree)
        ts = row.get("ts")
        if not isinstance(ts, str) or parse_ts(ts) is None:
            unparsed += 1
            continue
        death[tree] = ts                         # последняя запись о дереве главнее

    return ({t: first[t] for t in sorted(is_tree) if t in first},
            death, unparsed)


def tmp_sweep_declared(files: Sequence[str] = TMP_SWEEP_FILES,
                       read: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """Объявлена ли системная уборка `/tmp` — ОБЪЯВЛЕНИЕМ, а не догадкой о поведении.

    Исходов ЧЕТЫРЕ, и каждый отвечает на свой вопрос:

    * ``declared`` — строка есть, со значением: порог объявлен и его можно прочитать;
    * ``absent`` — файлы ПРОЧИТАНЫ, строки в них нет: уборка не задана;
    * ``mechanism_absent`` — файлов НЕ СУЩЕСТВУЕТ ни одного: самого механизма
      объявления на хосте нет (замер 10.10 на Darwin 27 — ровно этот исход);
    * ``unmeasured`` — файлы есть, но прочитать не удалось: сказать нечего.

    Разделять третий со вторым обязательно. «Порог не объявлен» есть утверждение о
    хосте; «механизма объявления нет» — признание, что прибор не знает, отсутствует
    уборка или он смотрит не туда. Склеить их значило бы выдать слепоту прибора за
    свойство хоста, а склеить любой из них с ``unmeasured`` — выдать «не смотрели» за
    «уборки нет» (инв. #17 наизнанку).
    """
    opener = read or (lambda p: Path(p).read_text(encoding="utf-8", errors="replace"))
    read_ok: List[str] = []
    values: List[str] = []
    missing: List[str] = []
    failures: List[str] = []
    for name in files:
        try:
            text = opener(name)
        except FileNotFoundError:
            missing.append(name)
            continue
        except OSError as exc:
            failures.append(f"{name}: {exc}")
            continue
        read_ok.append(name)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(TMP_SWEEP_KEY):
                values.append(f"{name}: {stripped}")

    if not read_ok and missing and not failures:
        return {"measured": True, "outcome": "mechanism_absent",
                "files_read": [], "files_missing": missing, "declarations": [],
                "reason": (f"ни одного файла объявления не существует ({', '.join(missing)}) "
                           f"— BSD-механизма periodic на хосте нет; отсутствует ли уборка "
                           f"/tmp или прибор смотрит не туда, ЭТОТ прибор не знает")}
    if not read_ok:
        return {"measured": False, "outcome": "unmeasured",
                "files_read": [], "files_missing": missing, "declarations": [],
                "reason": ("объявление системной уборки не прочитано: "
                           + "; ".join(failures + [f"{m}: нет файла" for m in missing]))}
    return {"measured": True,
            "outcome": "declared" if values else "absent",
            "files_read": read_ok,
            "files_missing": missing,
            "declarations": values,
            "reason": None if values else
                      (f"ключ {TMP_SWEEP_KEY} не объявлен ни в одном из прочитанных "
                       f"файлов ({', '.join(read_ok)}) — системная уборка /tmp не задана")}


# ------------------------------------------------------------------- срок жизни

def survival(trees: Dict[str, str],
             death: Dict[str, str],
             boot: Optional[datetime],
             *,
             now: datetime,
             birth_probe: Optional[Callable[[str], Optional[float]]] = None,
             exists: Optional[Callable[[str], bool]] = None) -> List[Dict[str, Any]]:
    """Наблюдённое выживание каждого дерева с НАЗВАННЫМ родом числа и причиной конца.

    Обе двери к ОС — живость каталога и его рождение — приняты ВХОДОМ (`exists`,
    `birth_probe`), как и момент (`now`) с загрузкой (`boot`): иначе тест судил бы о
    том, что сегодня лежит в `/tmp` этой машины, и краснел бы от календаря, а не от кода
    (`.claude/rules/deployment.md`, разделы про время и про личность процесса).
    """
    alive_probe = exists or (lambda p: Path(p).is_dir())
    born_probe = birth_probe or _birthtime

    rows: List[Dict[str, Any]] = []
    for tree, first_seen in trees.items():
        announced = parse_ts(first_seen)
        row: Dict[str, Any] = {"tree": tree, "first_announced": first_seen}
        if alive_probe(tree):
            born_at = born_probe(tree)
            if born_at is None:
                row.update({"cause": CAUSE_ALIVE, "measured": False,
                            "reason": "дерево живо, но рождение каталога не прочитано",
                            "survived_hours": None, "censored": True})
            else:
                born = datetime.fromtimestamp(born_at, tz=timezone.utc)
                row.update({"cause": CAUSE_ALIVE, "measured": True,
                            "born": born.strftime(_TS),
                            "birth_is_upper_bound": False,
                            "survived_hours": round((now - born).total_seconds() / 3600.0, 1),
                            # дерево ЕЩЁ живо ⇒ возраст это нижняя граница срока жизни
                            "censored": True})
            rows.append(row)
            continue

        ended = parse_ts(death.get(tree))
        if ended is not None:
            if announced is None:
                row.update({"cause": CAUSE_REAPED, "measured": False,
                            "reason": "квитанция есть, но первое объявление не разобрано",
                            "survived_hours": None, "censored": False})
            else:
                row.update({"cause": CAUSE_REAPED, "measured": True,
                            "ended": death[tree],
                            # рождение НЕ ПОЗЖЕ первого объявления ⇒ срок жизни снизу
                            "birth_is_upper_bound": True,
                            "survived_hours": round(
                                (ended - announced).total_seconds() / 3600.0, 1),
                            "censored": False})
            rows.append(row)
            continue

        # ни на диске, ни в квитанциях: конец есть, свидетеля конца нет
        if announced is None:
            row.update({"cause": CAUSE_VANISHED_SILENT, "measured": False,
                        "reason": "дерева нет, квитанции нет, объявление не разобрано",
                        "survived_hours": None, "censored": False})
        elif boot is not None and announced < boot:
            row.update({"cause": CAUSE_VANISHED_BOOT, "measured": False,
                        "reason": ("дерево объявлено до последней загрузки — исчезновение "
                                   "объясняет перезагрузка, срок жизни не наблюдён"),
                        "survived_hours": None, "censored": False})
        else:
            row.update({"cause": CAUSE_VANISHED_SILENT, "measured": False,
                        "reason": ("ни квитанции, ни архива, ни загрузки — конец дерева не "
                                   "назван ничем" if boot is not None else
                                   "ни квитанции, ни архива; время загрузки НЕ ИЗМЕРЕНО, "
                                   "поэтому перезагрузка как причина не проверена"),
                        "survived_hours": None, "censored": False})
        rows.append(row)
    return rows


def _birthtime(path: str) -> Optional[float]:
    """Рождение каталога, либо ``None`` — платформа его не отдаёт (не ноль, инв. #17)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    born = getattr(st, "st_birthtime", None)
    return float(born) if born else None


def boot_time(probe: Optional[Callable[[], Optional[float]]] = None) -> Tuple[Optional[datetime], Optional[str]]:
    """(момент последней загрузки, причина-если-не-измерено). Дверь — ВХОД."""
    if probe is not None:
        value = probe()
        return ((datetime.fromtimestamp(value, tz=timezone.utc), None) if value
                else (None, "время загрузки не отдано пробой"))
    try:                                          # pragma: no cover — живая ОС
        import subprocess
        out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True,
                             text=True, timeout=10)
        if out.returncode != 0:
            return None, f"sysctl kern.boottime код {out.returncode}"
        hit = re.search(r"sec\s*=\s*(\d+)", out.stdout)
        if not hit:
            return None, f"ответ sysctl не разобран: {out.stdout.strip()[:80]}"
        return datetime.fromtimestamp(int(hit.group(1)), tz=timezone.utc), None
    except Exception as exc:                      # noqa: BLE001 — «не измерено» это измерение
        return None, f"{type(exc).__name__}: {exc}"


def remaining_window(rows: Sequence[Dict[str, Any]],
                     sweep: Dict[str, Any],
                     uptime_hours: Optional[float]) -> Dict[str, Any]:
    """«Сколько осталось» — ТРЕТИЙ ИСХОД с тремя причинами, каждая ЗАМЕРОМ.

    Числом остаток не становится ни при каком состоянии входов, и это НЕ заглушка:
    каждая причина снимается своим наблюдением, и пока хоть одна стои́т, названный
    остаток был бы выдумкой. Если когда-нибудь снимутся все три (на хосте объявлена
    системная уборка · наблюдение переживёт аптайм · уборщик начнёт брать деревья с
    недоставленной работой), прибор обязан ответить числом — поэтому причины
    перечисляются ИЗМЕРЕННЫМИ, а не захардкожены.
    """
    reasons: List[Dict[str, Any]] = []

    survived = [r["survived_hours"] for r in rows
                if r.get("measured") and r.get("survived_hours") is not None]
    longest = max(survived) if survived else None
    if longest is not None and uptime_hours is not None and longest >= uptime_hours * 0.9:
        reasons.append({
            "reason": REASON_CEILING,
            "measured": True,
            "longest_survival_hours": longest,
            "uptime_hours": round(uptime_hours, 1),
            "says": ("макс. наблюдённое выживание упирается в аптайм — распределение "
                     "срезано ОКНОМ НАБЛЮДЕНИЯ, и любой квантиль из него говорит о том, "
                     "когда последний раз грузился хост, а не о сроке жизни дерева")})

    # Порог нельзя прочитать при ТРЁХ разных исходах двери, и каждый обязан дать
    # причину. Ветка только на `absent` молча теряла бы `mechanism_absent` — то есть
    # ровно тот исход, который даёт живой хост, и остаток оказался бы заблокирован
    # на одну причину меньше, чем измерено.
    sweep_outcome = sweep.get("outcome")
    if sweep_outcome == "absent":
        reasons.append({
            "reason": REASON_NO_TIMER, "measured": True,
            "says": ("системная уборка /tmp на хосте не объявлена — читать порог негде, "
                     "а выдумывать его заказ запретил прямо"),
            "files_read": sweep.get("files_read")})
    elif sweep_outcome == "mechanism_absent":
        reasons.append({
            "reason": REASON_NO_TIMER, "measured": True,
            "says": ("механизма объявления системной уборки на хосте нет вовсе — порога "
                     "не существует там, где его принято читать; есть ли уборка на самом "
                     "деле, этим прибором НЕ измерено"),
            "files_missing": sweep.get("files_missing")})
    elif not sweep.get("measured"):
        reasons.append({
            "reason": REASON_NO_TIMER, "measured": False,
            "says": "объявление системной уборки НЕ ПРОЧИТАНО — порога нет и проверить нечем",
            "detail": sweep.get("reason")})

    complete = [r for r in rows if r.get("measured") and r.get("cause") == CAUSE_REAPED]
    if complete:
        reasons.append({
            "reason": REASON_SELECTION, "measured": True,
            "complete_observations": len(complete),
            "all_from_reaper": True,
            "says": ("ВСЕ полные наблюдения срока жизни — деревья, которые уборщик ВЗЯЛ, "
                     "а он по построению (ADR-230) отказывается снимать дерево с "
                     "недоставленной работой; окно подъёма нужно ровно для тех деревьев, "
                     "которых в этой популяции нет — отбор по исходу")})

    return {"measured": False, "hours": None, "blocking_reasons": reasons,
            "says": ("остаток срока годности назвать нечем: " +
                     "; ".join(r["reason"] for r in reasons) if reasons else
                     "ни одна причина не измерена — вердикт об остатке НЕ ВЫНЕСЕН")}


def silent_loss_rate(rows: Sequence[Dict[str, Any]],
                     uptime_hours: Optional[float]) -> Dict[str, Any]:
    """Такт молчаливой потери: число G688 п. 4, с НАЗВАННЫМ направлением ошибки."""
    silent = [r["tree"] for r in rows if r.get("cause") == CAUSE_VANISHED_SILENT]
    if uptime_hours is None or uptime_hours <= 0:
        return {"measured": False, "trees": len(silent),
                "reason": "аптайм НЕ ИЗМЕРЕН — такт в сутки посчитать нечем",
                "per_day": None, "examples": silent[:10]}
    return {"measured": True, "trees": len(silent),
            "window_hours": round(uptime_hours, 1),
            "per_day": round(len(silent) / (uptime_hours / 24.0), 2),
            "is_lower_bound": True,
            "says": ("нижняя граница: дерево, не объявленное журналом вовсе, в население "
                     "не попадает — сколько их, предмет unannounced_divergence_scan"),
            "examples": silent[:10]}


# --------------------------------------------------------------------------- отчёт

def build_report(repo_root: Path,
                 *,
                 data_dir: Optional[Path] = None,
                 now: Optional[datetime] = None,
                 boot_probe: Optional[Callable[[], Optional[float]]] = None,
                 birth_probe: Optional[Callable[[str], Optional[float]]] = None,
                 exists: Optional[Callable[[str], bool]] = None,
                 sweep_files: Sequence[str] = TMP_SWEEP_FILES,
                 sweep_read: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """Отчёт прибора. Момент и ВСЕ двери к ОС — входы (см. `survival`)."""
    moment = now or datetime.now(timezone.utc)
    data = Path(data_dir) if data_dir else (Path(repo_root) / "data")

    journal, j_why = _read_jsonl(data / JOURNAL_NAME)
    ledger, l_why = _read_jsonl(data / REAP_LEDGER_NAME)

    base: Dict[str, Any] = {
        "generated_at": moment.strftime(_TS),
        "order": ORDER,
        "applied": False,
        "data_dir": str(data),
    }

    if not journal:
        base.update({"measured": False, "status": STATUS_UNMEASURED,
                     "reason": j_why or f"{JOURNAL_NAME}: записей нет — население мерить нечем"})
        # Объявленные поля несутся и в третьем исходе — ЯВНЫМ `None`, а не отсутствием.
        # Поле, которого читатель НЕ ВИДИТ, есть мёртвый свидетель (урок ADR-686): шаг
        # 0-офис сверяет объявленный `_READ_SCHEMA` с тем, что в документе, и на
        # пропущенных ключах докладывал бы «СХЕМА РАЗОШЛАСЬ» КАЖДЫЙ раз, когда прибор
        # честно отвечает «не измерено» — то есть ровно на верном поведении. `None` при
        # этом остаётся отличимым от нуля и от пустого раздела (инв. #17): `observed`
        # отдаёт на него «наблюдения нет».
        for field in ("population", "observation", "survival",
                      "remaining_window", "silent_loss"):
            base[field] = None
        return base

    trees, death, unparsed = population(journal, ledger)
    boot, boot_why = boot_time(boot_probe)
    uptime_hours = ((moment - boot).total_seconds() / 3600.0) if boot else None
    sweep = tmp_sweep_declared(sweep_files, read=sweep_read)
    rows = survival(trees, death, boot, now=moment,
                    birth_probe=birth_probe, exists=exists)

    by_cause: Dict[str, int] = {}
    for row in rows:
        by_cause[row["cause"]] = by_cause.get(row["cause"], 0) + 1

    base.update({
        "measured": True,
        "status": STATUS_MEASURED,
        "reason": None,
        "population": {
            "trees": len(rows),
            "by_cause": by_cause,
            "receipts": len(death),
            "receipts_unparsed": unparsed,
            "receipts_unparsed_says": (
                None if not unparsed else
                (f"{unparsed} квитанц. несут НЕ канонический формат отметки — "
                 "канонический разбор их отказывает, поэтому любому читателю по дате они "
                 "невидимы (класс ADR-682 на другом файле; дверь здесь НЕ расширена)")),
            "journal_note": j_why,
            "ledger_note": l_why,
        },
        "observation": {
            "boot": boot.strftime(_TS) if boot else None,
            "boot_unmeasured_reason": boot_why,
            "uptime_hours": round(uptime_hours, 1) if uptime_hours is not None else None,
            "tmp_sweep": sweep,
        },
        "survival": rows,
        "remaining_window": remaining_window(rows, sweep, uptime_hours),
        "silent_loss": silent_loss_rate(rows, uptime_hours),
    })
    return base


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = Path(data_dir) / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def format_report(report: Dict[str, Any]) -> List[str]:
    """Отрисовка ОДНОЙ копией по уже прочитанному документу (урок ADR-683)."""
    if not report.get("measured"):
        return [f"срок годности объявления владения: НЕ ИЗМЕРЕНО — {report.get('reason')}"]

    pop = observed(report, "population", kind=dict) or {}
    obs = observed(report, "observation", kind=dict) or {}
    rem = observed(report, "remaining_window", kind=dict) or {}
    loss = observed(report, "silent_loss", kind=dict) or {}
    causes = pop.get("by_cause") or {}

    out = [f"срок годности объявления владения ({report.get('generated_at')}):",
           f"  население одноразовых деревьев: {pop.get('trees')} "
           f"(живых {causes.get(CAUSE_ALIVE, 0)} · снято с квитанцией "
           f"{causes.get(CAUSE_REAPED, 0)} · исчезло: загрузка "
           f"{causes.get(CAUSE_VANISHED_BOOT, 0)}, БЕЗ СЛЕДА "
           f"{causes.get(CAUSE_VANISHED_SILENT, 0)})"]

    uptime = obs.get("uptime_hours")
    out.append(f"  окно наблюдения: аптайм "
               f"{'НЕ ИЗМЕРЕН' if uptime is None else f'{uptime:g}ч'} · "
               f"системная уборка /tmp: {(obs.get('tmp_sweep') or {}).get('outcome')}")

    if loss.get("measured"):
        out.append(f"  ТАКТ МОЛЧАЛИВОЙ ПОТЕРИ: {loss.get('trees')} дерев. за "
                   f"{loss.get('window_hours')}ч = {loss.get('per_day')}/сутки "
                   f"(нижняя граница)")
    else:
        out.append(f"  такт молчаливой потери: НЕ ИЗМЕРЕН — {loss.get('reason')} "
                   f"(деревьев без следа: {loss.get('trees')})")

    blocking = rem.get("blocking_reasons") or []
    if blocking:
        out.append("  СКОЛЬКО ОСТАЛОСЬ: НЕ ИЗМЕРИМО — " +
                   ", ".join(r.get("reason", "?") for r in blocking))
    else:
        # «причин нет» и «остаток назван» — РАЗНЫЕ вещи, и склеить их значило бы
        # прочитать пустой список как зелень (инв. #17).
        out.append("  СКОЛЬКО ОСТАЛОСЬ: вердикт НЕ ВЫНЕСЕН — ни одна причина не измерена")
    for item in blocking:
        mark = "" if item.get("measured") else " [сама причина НЕ ИЗМЕРЕНА]"
        out.append(f"     · {item.get('reason')}{mark}: {item.get('says')}")

    if pop.get("receipts_unparsed"):
        out.append(f"  [НЕ ИЗМЕРЕНО] {pop.get('receipts_unparsed_says')}")
    for note in (pop.get("journal_note"), pop.get("ledger_note"),
                 obs.get("boot_unmeasured_reason")):
        if note:
            out.append(f"  [НЕ ИЗМЕРЕНО] {note}")
    out.append("  НЕ ДОКЛАДЫВАЕТ: сколько деревьев НЕ ОБЪЯВЛЕНО вовсе (предмет "
               "unannounced_divergence_scan) · кто снял дерево без следа · что сделает "
               "перезагрузка (в наблюдении её ровно одна)")
    out.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False), деревьев не снимает")
    return out


def exit_code_for(report: Dict[str, Any]) -> int:
    """0 — потерь без следа нет · 1 — находка (есть потери либо остаток не измерим) · 2 — замера нет.

    Невозможность назвать остаток САМА является находкой: заказ просил число, и
    «числа нет по трём измеренным причинам» обязано быть видно как находка, а не как
    зелень. Зелёным прибор станет ровно тогда, когда и потерь без следа нет, и остаток
    назван, — то есть никогда молча.
    """
    if not report.get("measured"):
        return 2
    loss = observed(report, "silent_loss", kind=dict) or {}
    rem = observed(report, "remaining_window", kind=dict) or {}
    if not loss.get("measured") or int(loss.get("trees") or 0) > 0:
        return 1
    return 0 if rem.get("measured") else 1


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до шага 0-офис, иначе отсутствие файла неотличимо от
    «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    report = build_report(repo_root, now=now)
    try:
        save_artifact(report, repo_root / "data")
    except Exception as exc:  # noqa: BLE001 — прибор не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--data-dir", default=None, help="каталог данных (по умолчанию — свой)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать data/{ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    data_dir = Path(args.data_dir) if args.data_dir else None
    report = build_report(repo_root, data_dir=data_dir)
    if args.save:
        save_artifact(report, data_dir or (repo_root / "data"))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)
    return exit_code_for(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
