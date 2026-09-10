"""ПРОВОДКА или ЗНАЧЕНИЕ: почему у ноги книги нет живой ставки (заказ #546, ADR-306).

Заказ ADR-306 поставлен дословно так:

> **Почему у ``pendle`` нет живого провенанса ВООБЩЕ — и один ли он такой среди
> ног книги?** Мерить по ногам КНИГИ, разделяя два случая, в записи
> неотличимые: ногу не спрашивают (проводка) и ногу спрашивают, а живого
> значения нет. **Ловушка:** сегодняшний ``adapter_status.json`` отвечает про
> СЕГОДНЯ и про ДОРОГУ, а вопрос — про день прошлого и про ЗНАЧЕНИЕ (ADR-302).
> Что из прошлого поддаётся замеру, обязано быть ПЕРВЫМ результатом; не
> поддаётся ⇒ третий исход.

## Единица ответа

Пара **«день журнала × нога книг того дня»** — ровно то население, которое назвал
заказ. Книги дня = ``current_positions ∪ target_positions`` записи (то же чтение,
что у ``unevidenced_leg_causes``; см. ADR-290 о населении журнала).

## Два вопроса, и у каждого СВОЙ носитель прошлого

Прибор задаёт их в том порядке, в каком они отсекают, и НИ РАЗУ не спрашивает
``data/adapter_status.json``: этот файл отвечает про СЕГОДНЯ и про ДОРОГУ, а
вопрос — про день прошлого и про ЗНАЧЕНИЕ. Ловушка заказа соблюдена буквально:
имени этого файла в модуле нет.

**Вопрос 1 — спрашивали ли ногу в тот день (ПРОВОДКА).** Носитель — история git
файла ``spa_core/orchestrator/adapter_orchestrator.py``: состав опрашиваемого
набора есть ИСХОДНЫЙ КОД, а исходный код версионирован по дням. Прибор берёт
последний коммит с датой ``<= generated_at`` записи и читает список **по AST**,
не по подстроке.

**Вопрос 2 — наблюдал ли ЗНАЧЕНИЕ хоть кто-нибудь в тот день.** Носитель —
``data/adapter_feed_divergence_log.jsonl``: это единственный ДАТИРОВАННЫЙ
артефакт, который несёт наблюдение ставки по прогонам прошлого. Он говорит не
«что показал потребитель», а «что видели производители» в конкретную отметку.

## Пять исходов, и три из них — не ответ, а честное «не знаю»

* ``priced_live`` — у ноги в записи того дня ставка есть. Не дефект, в разбор
  причин не идёт;
* ``not_declared_polled`` — ключа НЕТ в объявленном наборе того дня. Проводка
  является достаточным объяснением, второго вопроса не требуется;
* ``polled_observed_elsewhere`` — ключ в наборе объявлен, и журнал расхождений
  того же дня доказывает, что живое значение наблюдал КТО-ТО из производителей.
  «Фид молчал» для этой пары ОПРОВЕРГНУТО: значение было, запись его не несёт;
* ``polled_value_unmeasured`` — ключ объявлен, доказательства наблюдения нет.
  **Третий исход, а не «фид молчал»:** журнал расхождений ОДНОСТОРОНЕН (см.
  ниже), и его молчание не есть отсутствие наблюдения;
* ``wiring_unmeasured`` — состав набора за тот день не прочитан (нет git, нет
  коммита раньше дня, ни одного из имён списка, или ОБА имени сразу). Третий
  исход обязателен: **``None``, приведённый к пустому множеству, назвал бы
  „не спрашивают“ КАЖДУЮ ногу** — замер на живом журнале 10.09 даёт при такой
  ошибке **51 пару из 179 по 13 дням**, все ложные.

## Одно имя — два объекта: список пережил ПЕРЕИМЕНОВАНИЕ

До цикла #274 (коммит ``0e96a2efd``, 17.08) опрашиваемый набор жил в том же
файле под именем ``ADAPTER_REGISTRY``; сегодня он зовётся ``POLLED_ADAPTERS``
(`.claude/rules/adapters.md`, «одно имя — один объект»). Журнал начинается
06.08 — то есть **одиннадцать первых его дней лежат ДО переименования**. Прибор
ищет ОБА имени; нашлись оба сразу ⇒ ``wiring_unmeasured``, потому что «который
из двух был опрашиваемым» решает не имя, а история, и догадка тут запрещена.

## Чего прибор НЕ утверждает — граница названа вслух

1. **git меряет ОБЪЯВЛЕННУЮ на origin дорогу, а не исполненную флотом.**
   Прод-дерево дрейфует от origin (`.claude/rules/deployment.md`), и отстающее
   дерево исполняет СТАРЫЙ список. Причём состав НЕ монотонен — замер по истории
   файла: 08.08 набор шёл 10 → 8 (откат ``3ff504d50``), — поэтому отставание
   способно дать и БОЛЬШИЙ набор, чем объявленный. Отсюда ``not_declared_polled``
   есть утверждение об ОБЪЯВЛЕНИИ, и так оно и названо в отчёте.
2. **Журнал расхождений ОДНОСТОРОНЕН.** Строку он оставляет только на
   ``CRITICAL``/``WARN``; род ``apy_both_literal`` («не наблюдал НИКТО») имеет
   тяжесть ``INFO`` и в журнал не попадает вовсе. Значит наличие строки
   ДОКАЗЫВАЕТ наблюдение, а отсутствие строки не доказывает ничего.
3. **Окно журнала расхождений короче журнала решений.** День вне окна —
   ``polled_value_unmeasured`` ПО ПОСТРОЕНИЮ, и прибор печатает границы окна
   рядом с числами, чтобы «не наблюдали» не читалось там, где «не смотрели».
4. **Какая ИМЕННО сторона наблюдала — прибор утверждает только там, где это
   лежит в полях.** Строки, написанные до этого цикла, несут сторону лишь в
   прозе сообщения; разбирать прозу прибор отказывается (подстрочный разбор
   переживает любое расплетение кода). Он опирается на РОД строки, а род есть
   структурное поле: три рода означают «живое наблюдение было хотя бы у одной
   стороны», и этого вопросу заказа достаточно.
5. **Прибор ничего не двигает.** ``POLLED_ADAPTERS``, пины, писатель журнала
   решений, ``MIN_HIT_RATE``, ``TriggerParams``, пороги RiskPolicy v1.0,
   стоп-кран и живой трек не трогаются ни на строку.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

OUTPUT_FILENAME = "leg_provenance_split.json"
JOURNAL_FILENAME = "allocation_rationale_history.jsonl"
DIVERGENCE_LOG_FILENAME = "adapter_feed_divergence_log.jsonl"

#: Файл, чья история отвечает на вопрос «спрашивали ли ногу в тот день».
ORCHESTRATOR_REL = os.path.join("spa_core", "orchestrator", "adapter_orchestrator.py")

#: Оба имени, под которыми жил ОДИН И ТОТ ЖЕ опрашиваемый набор. Порядок здесь
#: ничего не решает: если в одном коммите найдутся ОБА, прибор откажется судить.
POLLED_LIST_NAMES = ("POLLED_ADAPTERS", "ADAPTER_REGISTRY")

#: Роды строк журнала расхождений, каждый из которых ПО ПОСТРОЕНИЮ означает
#: «живое наблюдение ставки было хотя бы у одной стороны».
#:
#: Почему по роду, а не по прозе: сторона наблюдения (`live_side`) попадала в
#: журнал не всегда, а род — структурное поле с первого дня файла. Соответствие
#: рода и ветки-производителя закреплено тестом-храповиком: новый род у
#: `adapter_feed_divergence` обязан покраснеть здесь, а не тихо стать «не
#: наблюдали».
OBSERVED_KINDS = frozenset({
    "apy_literal_vs_live",     # одна сторона наблюдала, вторая подставила литерал
    "apy_live_vs_live",        # наблюдали обе и разошлись числом
    "apy_identity_mismatch",   # наблюдали обе, но РАЗНЫЕ пулы
    "pool_identity_mismatch",  # наблюдали обе, числа сошлись, пулы разные
})

#: Роды, которые о наблюдении ставки НЕ говорят ничего. Перечислены явно, чтобы
#: множество родов было ЗАМКНУТО: род вне обоих множеств ⇒ третий исход.
NEUTRAL_KINDS = frozenset({
    "apy_both_literal",  # не наблюдал никто (в журнал не пишется — INFO)
    "apy",               # тяжесть UNCHECKED: у одной из сторон нет ЧИСЛА вовсе,
                         # и о наблюдении ставки строка не говорит ничего
    "tier", "tier_mismatch",   # спор о тире — это потолок концентрации, не ставка
    # Роды про TVL. Живое наблюдение ТVL живой СТАВКИ не доказывает: это разные
    # поля разных путей адаптера (`_fetch_live_pool` против `_fetch_live_tvl`),
    # и зачесть их в пользу ставки значило бы ответить не на тот вопрос.
    "tvl", "tvl_mismatch", "tvl_live_vs_live", "tvl_provenance",
    "no_overlap",        # сторон не с чем сравнивать; протокол «-»
    "unchecked",         # сторож отказался судить
    "journal_opened",
})

CLASS_PRICED = "priced_live"
CLASS_NOT_POLLED = "not_declared_polled"
CLASS_OBSERVED = "polled_observed_elsewhere"
CLASS_VALUE_UNMEASURED = "polled_value_unmeasured"
CLASS_WIRING_UNMEASURED = "wiring_unmeasured"

DEFECT_CLASSES = (CLASS_NOT_POLLED, CLASS_OBSERVED,
                  CLASS_VALUE_UNMEASURED, CLASS_WIRING_UNMEASURED)

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"


# ── чтение входов ────────────────────────────────────────────────────────────

def _read_journal(data_dir: Path) -> Tuple[List[dict], Optional[str]]:
    path = Path(data_dir) / JOURNAL_FILENAME
    if not path.exists():
        return [], f"нет файла {JOURNAL_FILENAME}"
    out: List[dict] = []
    broken = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            broken += 1
            continue
        if isinstance(rec, dict):
            out.append(rec)
    if not out:
        return [], f"{JOURNAL_FILENAME} не дал ни одной записи"
    return out, (f"пропущено битых строк: {broken}" if broken else None)


def _read_divergence_log(data_dir: Path) -> Tuple[List[dict], Optional[str]]:
    path = Path(data_dir) / DIVERGENCE_LOG_FILENAME
    if not path.exists():
        return [], f"нет файла {DIVERGENCE_LOG_FILENAME}"
    out: List[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    if not out:
        return [], f"{DIVERGENCE_LOG_FILENAME} не дал ни одной записи"
    return out, None


# ── вопрос 1: проводка из истории git ────────────────────────────────────────

def parse_polled_names(source: str) -> Dict[str, List[str]]:
    """Ключи опрашиваемого набора ПО AST — для каждого из обоих имён отдельно.

    Разбор идёт по дереву, а не по подстроке: имя в комментарии, в докстроке или
    в чужом присваивании списком кортежей не должно решать вердикт.
    """
    found: Dict[str, List[str]] = {}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            target = node.targets[0].id
        if target in POLLED_LIST_NAMES and isinstance(node.value, ast.List):
            keys = [e.elts[0].value for e in node.value.elts
                    if isinstance(e, ast.Tuple) and e.elts
                    and isinstance(e.elts[0], ast.Constant)
                    and isinstance(e.elts[0].value, str)]
            if keys:
                found[target] = keys
    return found


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        res = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    return res.stdout


def polled_history(root: Path) -> Tuple[List[Tuple[str, str, Optional[Set[str]]]],
                                        Optional[str]]:
    """``[(committer_iso, sha, набор|None)]`` по возрастанию времени коммита.

    ``None`` в третьем поле — коммит, по которому состав НЕ прочитан (ни одного
    имени, либо ОБА сразу). Он не выбрасывается: пропуск такого коммита отдал бы
    его дни предыдущему составу, то есть выдал бы догадку за замер.
    """
    log = _git(root, "log", "--format=%H %cI", "--", ORCHESTRATOR_REL)
    if log is None:
        return [], "git недоступен или файл вне истории"
    rows: List[Tuple[str, str, Optional[Set[str]]]] = []
    for line in log.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, stamp = parts
        blob = _git(root, "show", f"{sha}:{ORCHESTRATOR_REL}")
        keys: Optional[Set[str]] = None
        if blob is not None:
            try:
                found = parse_polled_names(blob)
            except SyntaxError:
                found = {}
            if len(found) == 1:
                keys = set(next(iter(found.values())))
        rows.append((stamp, sha, keys))
    if not rows:
        return [], "история файла оркестратора пуста"
    rows.sort(key=lambda r: r[0])
    return rows, None


def declared_at(history: Sequence[Tuple[str, str, Optional[Set[str]]]],
                stamp: str) -> Tuple[Optional[Set[str]], Optional[str]]:
    """Состав, объявленный на момент ``stamp``. ``(набор|None, sha|None)``.

    Берётся ПОСЛЕДНИЙ коммит с датой ``<= stamp``; если состав по нему не
    прочитан — возвращается ``None``, а НЕ состав более раннего коммита.
    """
    chosen: Optional[Tuple[str, str, Optional[Set[str]]]] = None
    for row in history:
        if row[0] <= stamp:
            chosen = row
        else:
            break
    if chosen is None:
        return None, None
    return chosen[2], chosen[1]


# ── вопрос 2: наблюдение значения по датированному журналу расхождений ────────

def observation_index(rows: Sequence[dict]) -> Tuple[Dict[Tuple[str, str], List[str]],
                                                     List[str], List[str]]:
    """``({(день, нога): [роды]}, [дни окна], [неизвестные роды])``.

    Индекс строится ТОЛЬКО по родам из ``OBSERVED_KINDS``; окно считается по ВСЕМ
    строкам (иначе день, где расхождений не было, выпал бы из окна и стал бы
    неотличим от дня, когда никто не смотрел).
    """
    index: Dict[Tuple[str, str], List[str]] = {}
    days: Set[str] = set()
    unknown: Set[str] = set()
    for rec in rows:
        stamp = str(rec.get("observed_at") or "")
        day = stamp[:10]
        if len(day) != 10:
            continue
        days.add(day)
        kind = str(rec.get("kind") or "")
        if kind not in OBSERVED_KINDS and kind not in NEUTRAL_KINDS:
            unknown.add(kind)
            continue
        if kind not in OBSERVED_KINDS:
            continue
        protocol = str(rec.get("protocol") or "")
        if not protocol or protocol == "-":
            continue
        index.setdefault((day, protocol), []).append(kind)
    return index, sorted(days), sorted(unknown)


# ── замер ────────────────────────────────────────────────────────────────────

def _book_legs(rec: dict) -> List[str]:
    cur = rec.get("current_positions") or {}
    tgt = rec.get("target_positions") or {}
    legs: Set[str] = set()
    for book in (cur, tgt):
        if isinstance(book, dict):
            legs |= {str(k) for k in book}
    return sorted(legs)


def _priced(rec: dict, leg: str) -> bool:
    apy = rec.get("apy_evidenced_pct")
    if not isinstance(apy, dict):
        return False
    return apy.get(leg) is not None


def _stamp_of(rec: dict) -> str:
    stamp = rec.get("generated_at")
    if isinstance(stamp, str) and stamp:
        return stamp
    return f"{rec.get('cycle_date')}T23:59:59+00:00"


def measure(data_dir, *, root: Optional[str] = None,
            now: Optional[datetime] = None) -> dict:
    data_dir = Path(data_dir)
    root_path = Path(root) if root else Path(data_dir).parent
    now = now or datetime.now(timezone.utc)

    doc: dict = {
        "schema": "leg-provenance-split-v1",
        "generated_at": now.isoformat(),
        "order": "заказ #546 (ADR-306): проводка или значение — почему у ноги "
                 "книги нет живой ставки",
        "status": STATUS_UNMEASURED,
        "findings": [],
        # Ключи схемы объявляются СРАЗУ и значением `None`, а не нулями. Две
        # причины, и обе измерены. Первая: шаг 0-офис сверяет, что отчёт несёт
        # поля, которые производитель ПИШЕТ, — документ без них он честно
        # называет расхождением схемы. Вторая, и главная: ноль на месте
        # неизмеренного есть «не измерено, выданное за ответ» — `None` числом не
        # является и прочитан как измеренный ноль быть не может.
        "population": None,
        "class_counts": None,
        "pairs": None,
        "by_leg": None,
        "wiring_source": None,
        "observation_source": None,
        "none_coerced_to_empty_control": None,
        "does_not_report": "какая ИМЕННО сторона наблюдала на строках старой "
                           "формы (сторона лежала только в прозе сообщения, а "
                           "прозу прибор не разбирает) · была ли живая ставка у "
                           "ноги в день вне окна журнала расхождений",
        "advisory": "POLLED_ADAPTERS, пины, писатель журнала решений, "
                    "MIN_HIT_RATE, TriggerParams, пороги RiskPolicy v1.0, "
                    "стоп-кран и живой трек НЕ трогаются — прибор только "
                    "разделяет две причины",
    }
    findings: List[str] = doc["findings"]

    records, jnote = _read_journal(data_dir)
    doc["journal_rows"] = len(records)
    if not records:
        findings.append(f"[НЕ ИЗМЕРЕНО] журнал решений не прочитан: {jnote}")
        return doc
    if jnote:
        findings.append(f"[НЕ ИЗМЕРЕНО] {jnote}")

    history, hnote = polled_history(root_path)
    doc["wiring_source"] = {
        "file": ORCHESTRATOR_REL,
        "names_searched": list(POLLED_LIST_NAMES),
        "commits": len(history),
        "unreadable_commits": sum(1 for r in history if r[2] is None),
        "note": hnote,
    }
    if hnote:
        findings.append(f"[НЕ ИЗМЕРЕНО] проводка: {hnote} — вопрос 1 не задан "
                        f"ни по одной паре")

    div_rows, dnote = _read_divergence_log(data_dir)
    index, window_days, unknown_kinds = observation_index(div_rows)
    doc["observation_source"] = {
        "file": DIVERGENCE_LOG_FILENAME,
        "rows": len(div_rows),
        "window_first_day": window_days[0] if window_days else None,
        "window_last_day": window_days[-1] if window_days else None,
        "observed_kinds": sorted(OBSERVED_KINDS),
        "one_sided": True,
        "note": dnote,
    }
    if dnote:
        findings.append(f"[НЕ ИЗМЕРЕНО] наблюдение значения: {dnote} — вопрос 2 "
                        f"не задан ни по одной паре")
    if unknown_kinds:
        findings.append(
            f"[НЕ ИЗМЕРЕНО] журнал расхождений принёс род(ы), которых прибор не "
            f"знает: {', '.join(unknown_kinds)} — они не отнесены НИ к "
            f"наблюдению, НИ к его отсутствию")

    window = set(window_days)
    pairs: List[dict] = []
    counts = {c: 0 for c in (CLASS_PRICED, *DEFECT_CLASSES)}

    for rec in records:
        date = str(rec.get("cycle_date"))
        stamp = _stamp_of(rec)
        declared, sha = declared_at(history, stamp) if history else (None, None)
        for leg in _book_legs(rec):
            if _priced(rec, leg):
                counts[CLASS_PRICED] += 1
                continue
            if declared is None:
                cls = CLASS_WIRING_UNMEASURED
                kinds: List[str] = []
            elif leg not in declared:
                cls = CLASS_NOT_POLLED
                kinds = []
            else:
                kinds = sorted(set(index.get((date, leg)) or []))
                cls = CLASS_OBSERVED if kinds else CLASS_VALUE_UNMEASURED
            counts[cls] += 1
            pairs.append({
                "decision_date": date, "protocol": leg, "class": cls,
                "declared_polled": None if declared is None else (leg in declared),
                "wiring_commit": sha,
                "observation_kinds": kinds,
                "day_in_observation_window": date in window,
            })

    doc["class_counts"] = counts
    doc["pairs"] = pairs
    total = sum(counts.values())
    doc["population"] = {
        "leg_days_total": total,
        "leg_days_priced": counts[CLASS_PRICED],
        "leg_days_unpriced": total - counts[CLASS_PRICED],
    }

    # ── контроль: та же выдача, но `None` приведён к пустому множеству ────────
    # Ровно та ошибка, ради которой введён третий исход. Число печатается всегда,
    # даже когда оно ноль: контроль, молчащий при нуле, неотличим от контроля,
    # который не выполнялся.
    coerced = 0
    for rec in records:
        stamp = _stamp_of(rec)
        declared, _ = declared_at(history, stamp) if history else (None, None)
        if declared is not None:
            continue
        coerced += sum(1 for leg in _book_legs(rec) if not _priced(rec, leg))
    doc["none_coerced_to_empty_control"] = {
        "false_not_polled_pairs": coerced,
        "meaning": "столько пар назвал бы «ногу не спрашивают» прибор, который "
                   "принял бы нечитаемый состав за пустой набор",
    }

    # ── ответ ────────────────────────────────────────────────────────────────
    unpriced = doc["population"]["leg_days_unpriced"]
    findings.append(
        f"[ОТВЕТ] пар «день × нога книги» {total}, из них без живой ставки "
        f"{unpriced}: "
        + (" · ".join(f"{c}={counts[c]}" for c in DEFECT_CLASSES if counts[c])
           or "ни одной"))

    by_leg: Dict[str, Dict[str, int]] = {}
    for p in pairs:
        by_leg.setdefault(p["protocol"], {}).setdefault(p["class"], 0)
        by_leg[p["protocol"]][p["class"]] += 1
    doc["by_leg"] = by_leg
    for leg in sorted(by_leg):
        findings.append(
            f"[ПО НОГАМ] {leg}: "
            + " · ".join(f"{c}={n}" for c, n in sorted(by_leg[leg].items())))
    for p in pairs:
        findings.append(
            f"[ПО ДНЯМ] {p['decision_date']} {p['protocol']} — {p['class']}"
            + (f" (роды: {', '.join(p['observation_kinds'])})"
               if p["observation_kinds"] else ""))

    if counts[CLASS_NOT_POLLED] == 0 and unpriced:
        doc["status"] = STATUS_CRITICAL
        findings.append(
            f"[CRITICAL] ПРОВОДКА НЕ ОБЪЯСНЯЕТ НИ ОДНОЙ ПАРЫ: все {unpriced} "
            f"ног без живой ставки были в объявленном опрашиваемом наборе "
            f"своего дня. Рычаг лежит НЕ в POLLED_ADAPTERS — вопрос заказа "
            f"переадресуется значению, а не дороге")
    if counts[CLASS_OBSERVED]:
        doc["status"] = STATUS_CRITICAL
        findings.append(
            f"[CRITICAL] на {counts[CLASS_OBSERVED]} парах живое значение в тот "
            f"день НАБЛЮДАЛОСЬ производителем, а запись решения его не несёт — "
            f"«фид молчал» для них опровергнуто датированным журналом "
            f"расхождений, потеря лежит между наблюдением и записью")
    if counts[CLASS_VALUE_UNMEASURED]:
        findings.append(
            f"[НЕ ИЗМЕРЕНО] {counts[CLASS_VALUE_UNMEASURED]} пар: ногу "
            f"спрашивали, доказательства наблюдения нет. Журнал расхождений "
            f"односторонен (род «не наблюдал никто» имеет тяжесть INFO и в него "
            f"не пишется), поэтому молчание журнала НЕ означает молчания фида")
    if counts[CLASS_WIRING_UNMEASURED]:
        findings.append(
            f"[НЕ ИЗМЕРЕНО] {counts[CLASS_WIRING_UNMEASURED]} пар: состав "
            f"опрашиваемого набора за их день не прочитан — вопрос 1 остался "
            f"без ответа, и вопрос 2 по ним не задавался")
    findings.append(
        f"[КОНТРОЛЬ] «None как пустой набор» назвал бы непрошенными "
        f"{coerced} пар(ы) — столько стоит отказ от третьего исхода")

    if doc["status"] != STATUS_CRITICAL:
        doc["status"] = (STATUS_WARNING
                         if counts[CLASS_VALUE_UNMEASURED]
                         or counts[CLASS_WIRING_UNMEASURED]
                         else STATUS_OK)
    return doc


def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: население → носители → классы → дни."""
    out: List[str] = []
    pop = doc.get("population") or {}
    out.append(f"   проводка или значение (заказ #546): {doc.get('status')} · "
               f"дней журнала {doc.get('journal_rows')} · пар "
               f"{pop.get('leg_days_total')} · без ставки "
               f"{pop.get('leg_days_unpriced')}")
    ws = doc.get("wiring_source") or {}
    if ws:
        out.append(f"   вопрос 1 (проводка): история {ws.get('file')} — "
                   f"коммитов {ws.get('commits')}, нечитаемых "
                   f"{ws.get('unreadable_commits')}")
    os_ = doc.get("observation_source") or {}
    if os_:
        out.append(f"   вопрос 2 (значение): {os_.get('file')} — строк "
                   f"{os_.get('rows')}, окно "
                   f"{os_.get('window_first_day')}..{os_.get('window_last_day')} "
                   f"(односторонний)")
    # НЕ `or {}`: у неизмеренного документа здесь лежит `None`, и подмена его
    # пустым словарём — ровно та «подстановка ответа вместо замера», против
    # которой написан сам прибор (и храповик `test_absent_observation_ratchet`).
    counts = doc.get("class_counts")
    if counts:
        out.append("   классы: " + " · ".join(f"{c}={n}" for c, n in counts.items() if n))
    for line in doc.get("findings") or []:
        out.append(f"   {line}")
    if doc.get("does_not_report"):
        out.append(f"   НЕ ДОКЛАДЫВАЕТ: {doc['does_not_report']}")
    if doc.get("advisory"):
        out.append(f"   ADVISORY: {doc['advisory']}")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, **kwargs) -> dict:
    """Форма, которую ждут ступень переписей `findings_bridge` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = measure(data_dir, root=root, now=now, **kwargs)
    findings = list(doc.get("findings") or [])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for x in findings if x.startswith("[CRITICAL]")),
        "warn": sum(1 for x in findings if x.startswith("[ПО НОГАМ]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ")
                    or x.startswith("[ПО ДНЯМ]")
                    or x.startswith("[КОНТРОЛЬ]")),
        # «не измерено» считается ОТДЕЛЬНО от нулей: растворив его, мы сделали бы
        # молчание прибора неотличимым от чистого прогона.
        "unchecked": (1 if doc["status"] == STATUS_UNMEASURED else 0)
                     + sum(1 for x in findings if x.startswith("[НЕ ИЗМЕРЕНО]")),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="проводка или значение: почему у ноги книги нет живой "
                    "ставки (заказ #546)")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--root", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    data_dir = (Path(args.data_dir) if args.data_dir
                else Path(os.environ.get("SPA_DATA_DIR")
                          or (Path(__file__).resolve().parents[2] / "data")))
    root = args.root or str(Path(data_dir).parent)
    doc = measure(data_dir, root=root)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(data_dir) / OUTPUT_FILENAME))
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
