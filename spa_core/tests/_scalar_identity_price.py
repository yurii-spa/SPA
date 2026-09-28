#!/usr/bin/env python3
"""Цена смены правила личности: КТО держит позиционную координату.

**Живёт рядом с тестом, а не в `scripts/`, и это решение, а не удобство.** Первая
редакция была скриптом `scripts/measure_scalar_identity_price.py` — и храповик
`test_unwired_scripts_ratchet` покраснел верно: у скрипта не было вызывающего.
Дописать имя в его базу запрещено, а заводить plist ради меры, которая обязана
держать НОЛЬ всю жизнь репозитория, значило бы отвечать расписанием на вопрос
инварианта. Утверждение «чужих держателей позиционной координаты нет» проверяется
на КАЖДОМ прогоне CI, и читатель у него — сам прогон. Это ровно тот урок, который
заказ G35 назвал пунктом 5: число без читателя есть «построено и не
зарегистрировано».

Заказ **G35, п. 3** приказа владельца «Portfolio CIO» (он же **G37, п. 4**)
требует порядок: *«Цена — чужие координаты у всей семьи обходов, поэтому сначала
замер цены, потом правка»*. Этот прибор и есть замер, и он остаётся сторожем
после правки — в обратную сторону.

## Вопрос, на который прибор отвечает

Координата вида ``.protocols[3]`` называет элемент МЕСТОМ. Правило
``element_identity``/``BY_VALUE`` (ADR-502) называет элемент-скаляр его
ЗНАЧЕНИЕМ: ``.protocols[="aave_v3"]``. Внутри одного прогона это безопасно по
построению — множество ``drop`` считается тем же правилом, что пишет координату,
поэтому обе стороны едут вместе. Опасен **держатель через прогон**: кто записал
позиционную координату себе и будет сверять её ПОТОМ. У него имя перестанет
находиться, и «ничего не снято» прочтётся как «нечего было снимать» — ровно
та тихая поломка, о которой предупреждает docstring ``indexed``.

Поэтому прибор спрашивает не «сколько координат изменится» (это число внутри
прогона ничего не стоит), а **сколько координат держит кто-то ЧУЖОЙ**.

## Три рода держателя — и они различимы (инв. #17)

* ``regenerated`` — координата лежит в артефакте, который его производитель
  перезаписывает каждый прогон. Держателем не является: сверять её не с чем.
* ``foreign`` — координата лежит там, где её будут СВЕРЯТЬ позже: критерий
  карточки (``finding_key:``/``acceptance_probe:``), храповиковая база,
  конфигурация. Это и есть цена, и она обязана быть нулём.
* ``test_literal`` — координата в тест-файле. Ценой не считается: тест меняется
  осознанно и вслух (инв. #16), а не ломается молча. Печатается отдельно,
  чтобы «ноль чужих» не читалось как «ничего не придётся править».

**Чего прибор НЕ доказывает.** Что найденная координата действительно проходит
через список скаляров: для этого её надо разрешить против живого объекта, а
объекта у держателя может не быть вовсе. Мера односторонняя и сильна в нужную
сторону — она ошибается в сторону НАХОДКИ (посчитает позиционную координату
чужой, даже если та упирается в список словарей), и ноль у неё поэтому значит
«держателей нет», а не «мы не нашли».

Только stdlib, оффлайн, ничего не пишет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

_ROOT = Path(__file__).resolve().parents[2]

#: Координата семьи обходов, ЗАПИСАННАЯ КАК СТРОКА. Кавычка — не деталь разбора,
#: а сам предмет: держатель хранит координату ДАННЫМИ, чтобы свериться с нею
#: потом. Первая редакция искала её без кавычек, «чтобы ошибаться в сторону
#: находки», и намерила 615 «чужих держателей», из которых настоящих НОЛЬ: под
#: меру попал питоний код `Path(__file__).resolve().parents[1]`. Грубость
#: полезна ВНУТРИ класса и обманна, когда расширяет сам класс, — та мера
#: отвечала на вопрос «где в репозитории точка со скобками».
_COORD = re.compile(r"""["'](\.[A-Za-z_][A-Za-z0-9_.\[\]=+\- ]{0,200})["']""")
_POSITIONAL = re.compile(r"\[\d+\]")

#: Критерий карточки — держатель, который координату СВЕРЯЕТ машинно.
_CRITERION = re.compile(r"^(?:finding_key|acceptance_probe):\s*(\S.*?)\s*$", re.M)

#: Расширения, в которых вообще осмысленно искать записанную координату.
_TEXTUAL = {".json", ".md", ".py", ".yaml", ".yml", ".txt", ".jsonl"}


def tracked_files(root: Path) -> Tuple[List[Path], str]:
    """Git-tracked файлы. Не спросили git ⇒ НЕ ИЗМЕРЕНО с причиной.

    Спрашивается именно git, а не обход диска: рабочее дерево полно чужого
    мусора и одноразовых стендов, и посчитать их держателями значило бы
    придумать цену.
    """
    try:
        proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                              capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"git ls-files не позван: {type(exc).__name__}"
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-200:]
        return [], f"git ls-files вышел кодом {proc.returncode}: {tail}"
    names = [n for n in proc.stdout.decode("utf-8", "replace").split("\0") if n]
    if not names:
        return [], "git ls-files вернул пустой список — мерить нечего"
    return [root / n for n in names], ""


def _committed(root: Path, rel: str) -> Tuple[str, str]:
    """Содержимое файла из ``HEAD`` — для тех, кого git знает, а диск нет."""
    try:
        proc = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{rel}"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"git show не позван: {type(exc).__name__}"
    if proc.returncode != 0:
        return "", f"нет ни на диске, ни в HEAD (код {proc.returncode})"
    return proc.stdout.decode("utf-8", "replace"), ""


def _kind(rel: str) -> str:
    """Род держателя по тому, КАК он держит координату.

    Род решает не важность файла, а то, сверяется ли координата потом машинно.
    Карточка разобрана ОТДЕЛЬНО (``_criterion_coords``): в её прозе координата
    ЦИТИРУЕТСЯ — сам приказ приводит ``.findings[8].severity`` примером
    позиционной лжи, — а сверяется только значение критерия. Считать прозу
    держателем значило бы назвать ценой собственный текст объяснения.
    """
    if rel.startswith("data/"):
        return "regenerated"
    if "/tests/" in rel or rel.startswith("tests/") or "/test_" in f"/{rel}":
        return "test_literal"
    if rel.endswith("_baseline.json"):
        return "foreign"
    if rel.endswith(".md") or rel.startswith("landing/"):
        # Документ, карточка и страница координату не СВЕРЯЮТ — они её цитируют.
        # Цитата устаревает громко (её читает человек), а не тихо.
        return "quoted"
    return "foreign"


def _criterion_coords(text: str) -> List[str]:
    """Позиционные координаты в ЗНАЧЕНИИ критерия карточки.

    Единственная форма, в которой карточка держит координату машинно: мост
    сверяет ``finding_key``, очередь — ``acceptance_probe``. Кавычек тут нет,
    поэтому и мера своя.
    """
    return sorted({m.group(1) for m in _CRITERION.finditer(text)
                   if _POSITIONAL.search(m.group(1))})


def measure(root: Path) -> dict:
    """Перепись держателей позиционной координаты. Незакрытое звено ⇒ UNMEASURED."""
    doc: dict = {
        "schema": "scalar_identity_price.v1",
        "question": ("кто держит позиционную координату через прогон и потому "
                     "сломался бы молча от правила личности-по-значению"),
        "what_it_does_not_prove": [
            "что найденная координата действительно упирается в список скаляров: "
            "мера односторонняя и ошибается в сторону НАХОДКИ",
            "что держатель координаты сверяет её машинно — род определён МЕСТОМ "
            "файла, а не чтением его кода",
        ],
        "advisory": ("прибор только ЧИТАЕТ: ни одной координаты, ни артефакта, "
                     "ни RiskPolicy, ни живого трека он не трогает"),
    }
    files, cause = tracked_files(root)
    if cause:
        doc["status"] = "UNMEASURED"
        doc["reason"] = cause
        return doc

    holders: Dict[str, Dict[str, List[str]]] = {}
    scanned = 0
    from_commit = 0
    unreadable: List[str] = []
    for path in files:
        if path.suffix.lower() not in _TEXTUAL:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            # Git файл ЗНАЕТ, а на диске его нет. Это НЕ «не прочитан» и НЕ
            # «пуст»: в боевом дереве так лежат четыре файла (замер 28.09),
            # и обе подмены были бы неверны — «не измерено» на всю перепись
            # сделало бы прибор вечно молчащим именно там, где он нужен, а
            # пустая строка тихо вынесла бы файл из знаменателя. Спрашиваем
            # содержимое у КОММИТА: вопрос-то про репозиторий.
            text, cause = _committed(root, str(path.relative_to(root)))
            if cause:
                unreadable.append(f"{path.relative_to(root)}: {cause}")
                continue
            from_commit += 1
        except OSError as exc:
            unreadable.append(f"{path.relative_to(root)}: {type(exc).__name__}")
            continue
        scanned += 1
        rel = str(path.relative_to(root))
        found = {m.group(1) for m in _COORD.finditer(text)
                 if _POSITIONAL.search(m.group(1))}
        if found:
            holders.setdefault(_kind(rel), {})[rel] = sorted(found)
        # Критерий карточки — вторая, НЕ кавычечная форма того же держателя.
        # Сложить её в общую меру нельзя: разбор другой, и род другой.
        if rel.startswith("nimbalyst-local/tracker/"):
            crit = _criterion_coords(text)
            if crit:
                holders.setdefault("foreign", {}).setdefault(rel, []).extend(crit)

    # Файл, который не прочитан, — это НЕ «в нём ничего нет». Знаменатель без
    # него неполон, и молчать об этом значило бы выдать «не измерено» за «чисто».
    if unreadable:
        doc["status"] = "UNMEASURED"
        doc["reason"] = (f"не прочитано файлов: {len(unreadable)} — "
                         f"{'; '.join(unreadable[:5])}")
        doc["unreadable"] = unreadable
        return doc

    counts = {kind: sum(len(c) for c in per_file.values())
              for kind, per_file in sorted(holders.items())}
    doc["files_scanned"] = scanned
    # Сколько из них прочитано не с диска, а из коммита. Число печатается
    # рядом, чтобы «прочитано 7424» не читалось как «7424 лежат в дереве».
    doc["files_read_from_commit"] = from_commit
    doc["counts"] = counts
    doc["holders"] = {kind: per_file for kind, per_file in sorted(holders.items())}
    foreign = counts.get("foreign", 0)
    if foreign:
        doc["status"] = "FINDING"
        doc["reason"] = (f"позиционную координату держат ЧУЖИЕ: {foreign} в "
                         f"{len(holders.get('foreign', {}))} файл(ах) — правило "
                         f"личности сменило бы им имя молча")
    else:
        doc["status"] = "OK"
        doc["reason"] = ("чужих держателей позиционной координаты НЕТ, и это "
                         "измерено: цена правила личности-по-значению равна нулю "
                         "вне перезаписываемых артефактов и тестов")
    return doc


def render(doc: dict) -> str:
    lines = [f"[{doc['status']}] {doc['reason']}"]
    if doc.get("files_scanned") is not None:
        lines.append(f"  прочитано файлов: {doc['files_scanned']}"
                     f" (из коммита, не с диска: {doc['files_read_from_commit']})")
    for kind, n in (doc.get("counts") or {}).items():
        lines.append(f"  {kind}: {n} координат(ы) в "
                     f"{len(doc['holders'][kind])} файл(ах)")
    for rel, coords in sorted((doc.get("holders") or {}).get("foreign", {}).items()):
        lines.append(f"  ЧУЖОЙ ДЕРЖАТЕЛЬ {rel}: {', '.join(coords[:4])}")
    lines.append("НЕ ДОКАЗЫВАЕТ: " + "; ".join(doc["what_it_does_not_prove"]))
    return "\n".join(lines)


#: Три исхода — три РАЗНЫХ имени (инв. #17). Слей любые два, и «не измерено»
#: станет неотличимо от «держателей нет» — тот самый fail-OPEN, который этот
#: прибор и ищет у других.
STATUSES = ("OK", "FINDING", "UNMEASURED")
