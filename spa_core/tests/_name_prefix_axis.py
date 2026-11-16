"""Упоминание, которое нельзя ПРИПИСАТЬ субъекту, проводкой не является.

# LLM_FORBIDDEN

Храповик `test_unwired_guard_modules_ratchet` спрашивает, встречается ли стем
модуля хоть в одном не-тестовом файле дерева (`stem in body` — подстрока
текста). Соседи сузили поверхность доказательства: `_mention_wiring`
(ADR-1027) спросил, достижим ли сам упоминающий, `_call_wiring` (ADR-1028) —
зовёт ли он упоминаемого. Все трое при этом верят, что найденные СИМВОЛЫ
говорят о субъекте.

Эта дверь — про то, что символы могут говорить о чём-то ДРУГОМ, и ни одно
ужесточение стриппера такого вхождения не снимет: текст там настоящий код,
прозой он не является и комментарием тоже. Пример, названный ADR-1028 п. 6:
стем `agent_passport` встречается в имени `agent_passports` — девять раз в
семи файлах, и ни одно из девяти вхождений о субъекте не говорит.

## Три степени ПРИПИСЫВАЕМОСТИ одного вхождения

* `QUALIFIED` — вхождение входит в ссылку, которая называет и СВОЙ КАТАЛОГ
  субъекта (`spa_core.monitoring.foo`, `from spa_core.monitoring import foo`,
  путь-литерал `spa_core/monitoring/foo`). Двусмысленности нет ни при каком
  омониме.
* `BARE` — вхождение стоит на границах идентификатора, но каталога не несёт.
  Приписать его субъекту можно ТОЛЬКО если стем в дереве уникален.
* `GLUED` — вхождение лежит ВНУТРИ более длинного идентификатора
  (`agent_passport` ⊂ `agent_passports`). Оно называет не субъекта.

## Три исхода у субъекта (инвариант #17)

* `ATTRIBUTED` — есть `QUALIFIED`, либо есть `BARE` при уникальном стеме;
* `AMBIGUOUS` — субъекта упоминают (depth-1 храповик числит подключённым), но
  ни одно вхождение приписать ему нельзя: все `GLUED`, либо все `BARE` при
  неуникальном стеме. **Предмет класса.**
* `CENSUS` — субъекта не упоминает НИКТО; он уже на учёте у храповика и
  предметом ЭТОГО класса не является.

«Не измерено» — ОТДЕЛЬНЫЙ исход, а не ноль: нечитаемый файл поверхности и
тонкая поверхность поднимают `Unmeasured`, CLI выходит кодом **2**.

## Знак ошибки объявлен: население есть ПОЛ, а не потолок

Признак `ATTRIBUTED` намеренно ЩЕДРЫЙ — ошибаться он обязан в сторону
«проводка цела», чтобы найденное было находкой, а не подозрением:

* одного `QUALIFIED`-вхождения достаточно, и прочитано ли оно кем-нибудь,
  прибор не спрашивает (это вопрос соседей ADR-1027/1028);
* `BARE` при уникальном стеме засчитан, хотя такое вхождение может быть просто
  словом в строке сообщения;
* уникальность стема мерится по ПОВЕРХНОСТИ СКАНА (`.py` в
  `spa_core`/`scripts`/`launchd`/`architecture`, без `tests`/`archive`), и
  омоним за её пределами прибор не увидит.

Поэтому утверждать по этому числу «больше членов нет» ЗАПРЕЩЕНО.

## Ось, ради которой заказан замер, и почему её мало

Заказ G1017 п. 2 спросил ПАРЫ субъектов, где стем одного есть подстрока имени
другого. Прибор их считает (`pairs`), но вердикт по ним НЕ выносит: быть в
такой паре и быть слепым — разные вещи. Субъект с парой может иметь честное
`QUALIFIED`-упоминание в другом файле, а слепой субъект может не иметь пары
вовсе (`apy_drift_alert` приклеен к имени ДАННЫХ `apy_drift_alerts.json`, а не
к имени субъекта). Отношение «пара» классу ни достаточно, ни необходимо — и
это замер, а не оговорка.

ADVISORY: прибор только ЧИТАЕТ. Ни один сторож, ни одна база, ни
`KNOWN_UNWIRED` им не меняются.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Dict, List, Optional

from spa_core.tests import _mention_wiring as _mw

#: Поверхность, субъекты, стрипперы и пол непустоты — у соседа, своей копии нет.
#: Правило «что считается упоминанием» живёт в ОДНОМ месте (урок ADR-1028).
SCAN_SUBDIRS = _mw.SCAN_SUBDIRS
MIN_SUBJECTS = _mw.MIN_SUBJECTS

CENSUS = "CENSUS"
ATTRIBUTED = "ATTRIBUTED"
AMBIGUOUS = "AMBIGUOUS"

QUALIFIED, BARE, GLUED = "QUALIFIED", "BARE", "GLUED"

_IDENT = re.compile(r"[A-Za-z0-9_]")

_ROOT = pathlib.Path(__file__).resolve().parents[2]


class Unmeasured(RuntimeError):
    """Поверхность не прочитана или тонка — это НЕ ноль находок."""


def _occurrences(body: str, needle: str) -> List[int]:
    """Все индексы вхождения. Перекрытия считаются — шаг ровно 1 символ."""
    out, k = [], 0
    while True:
        j = body.find(needle, k)
        if j < 0:
            return out
        out.append(j)
        k = j + 1


def _is_glued(body: str, at: int, needle: str) -> bool:
    """Вхождение лежит внутри более длинного идентификатора."""
    end = at + len(needle)
    left = at > 0 and bool(_IDENT.match(body[at - 1]))
    right = end < len(body) and bool(_IDENT.match(body[end]))
    return left or right


def qualified_forms(module: str) -> List[str]:
    """Ссылки, называющие СВОЙ каталог субъекта. Омоним их не подделывает."""
    p = pathlib.Path(module)
    pkg = str(p.parent).replace("/", ".")
    return [f"{pkg}.{p.stem}",
            f"from {pkg} import {p.stem}",
            f"{p.parent}/{p.stem}"]


def grade_mentions(module: str, texts: Dict[str, str], *,
                   stem_unique: bool) -> dict:
    """Степени приписываемости всех вхождений стема субъекта."""
    stem = pathlib.Path(module).stem
    forms = qualified_forms(module)
    grades: Dict[str, int] = {QUALIFIED: 0, BARE: 0, GLUED: 0}
    where: Dict[str, List[str]] = {QUALIFIED: [], BARE: [], GLUED: []}
    for path, body in sorted(texts.items()):
        if path == module:          # файл сам себе упоминанием не является
            continue
        for at in _occurrences(body, stem):
            if _is_glued(body, at, stem):
                # Приклеенное вхождение всё ещё может быть КВАЛИФИЦИРОВАННЫМ:
                # `spa_core.monitoring.foo` приклеивает стем слева точкой — нет,
                # точка не идентификатор; а вот `.../foo.py` приклеивает справа
                # точкой — тоже нет. Склеивает только идентификаторный символ,
                # поэтому квалифицированная форма проверяется ОТДЕЛЬНО ниже.
                grades[GLUED] += 1
                if len(where[GLUED]) < 8:
                    where[GLUED].append(path)
                continue
            if any(f in body for f in forms):
                grades[QUALIFIED] += 1
                if len(where[QUALIFIED]) < 8:
                    where[QUALIFIED].append(path)
            else:
                grades[BARE] += 1
                if len(where[BARE]) < 8:
                    where[BARE].append(path)
    total = sum(grades.values())
    if total == 0:
        verdict = CENSUS
    elif grades[QUALIFIED] or (grades[BARE] and stem_unique):
        verdict = ATTRIBUTED
    else:
        verdict = AMBIGUOUS
    return {"module": module, "stem": stem, "verdict": verdict,
            "grades": grades, "where": where, "stem_unique": stem_unique}


def stem_population(root: pathlib.Path) -> Dict[str, List[str]]:
    """{стем: [пути]} по `.py` поверхности скана — область НАЗВАНА, не подразумевается."""
    out: Dict[str, List[str]] = {}
    seen = False
    for sub in SCAN_SUBDIRS:
        base = root / sub
        if not base.exists():
            continue
        for f in sorted(base.rglob("*.py")):
            rel = str(f.relative_to(root))
            if "/tests/" in rel or "/archive/" in rel:
                continue
            seen = True
            out.setdefault(f.stem, []).append(rel)
    if not seen:
        raise Unmeasured(
            "в поверхности скана не нашлось ни одного `.py` — «омонимов нет» "
            "значило бы «мерить было нечем»")
    return out


def subject_pairs(subjects: List[str]) -> List[dict]:
    """Ось, заказанная дословно: стем A есть подстрока ИМЕНИ другого субъекта B."""
    pairs = []
    for a in subjects:
        sa = pathlib.Path(a).stem
        for b in subjects:
            if a == b:
                continue
            nb = pathlib.Path(b).name
            if sa in nb and sa != pathlib.Path(b).stem:
                pairs.append({"stem": sa, "inside": nb, "subject": a, "other": b})
    return pairs


def measure(root: Optional[pathlib.Path] = None,
            min_subjects: int = MIN_SUBJECTS) -> dict:
    """ОДИН замер. Поднимает `Unmeasured`, если мерить нечем."""
    base = (pathlib.Path(root) if root is not None else _ROOT).resolve()
    try:
        subj = _mw.subjects(base)
        texts = _mw.tree_texts(base)
    except _mw.Unmeasured as exc:
        raise Unmeasured(str(exc)) from exc
    if len(subj) < min_subjects:
        raise Unmeasured(
            f"субъектов всего {len(subj)} при поле {min_subjects} — скан сузился, "
            "и «членов класса нет» значило бы «мерить было нечем»")
    stems = stem_population(base)
    rows = []
    for m in subj:
        same = [p for p in stems.get(pathlib.Path(m).stem, []) if p != m]
        row = grade_mentions(m, texts, stem_unique=not same)
        row["homonyms"] = same
        rows.append(row)
    # Качество доказательства — ОТДЕЛЬНЫЙ вопрос от вердикта, и он важнее числа
    # членов: храповик может быть ПРАВ о проводке и при этом неправ о причине.
    ev = {QUALIFIED: 0, BARE: 0, GLUED: 0}
    for r in rows:
        for k in ev:
            ev[k] += r["grades"][k]
    seen_total = sum(ev.values())
    by = {r["module"]: r["verdict"] for r in rows}
    pairs = subject_pairs(subj)
    ambiguous = sorted(r["module"] for r in rows if r["verdict"] == AMBIGUOUS)
    pair_members = sorted({p["subject"] for p in pairs})
    return {
        "measured_at": _mw._dt.datetime.now(_mw._dt.timezone.utc).isoformat(),
        "root": str(base),
        "subjects": len(subj),
        "census": sorted(r["module"] for r in rows if r["verdict"] == CENSUS),
        "attributed": sum(1 for r in rows if r["verdict"] == ATTRIBUTED),
        "ambiguous": ambiguous,
        "homonym_candidates": sorted(r["module"] for r in rows if r["homonyms"]),
        "pairs": pairs,
        "pair_members": pair_members,
        "pair_members_ambiguous": sorted(set(pair_members) & set(ambiguous)),
        "ambiguous_outside_pairs": sorted(set(ambiguous) - set(pair_members)),
        "evidence": ev,
        "evidence_total": seen_total,
        "evidence_attributable_share": (
            round(ev[QUALIFIED] / seen_total, 4) if seen_total else None),
        "majority_unattributable": sorted(
            r["module"] for r in rows
            if sum(r["grades"].values())
            and r["grades"][QUALIFIED] * 2 < sum(r["grades"].values())),
        "rows": rows,
        "status": by,
        "floor_not_ceiling": True,
    }


def report(doc: dict) -> List[str]:
    """Строки для человека. Ноль печатается ОТДЕЛЬНОЙ строкой, а не молчанием."""
    out = [f"ось ПРИПИСЫВАЕМОСТИ упоминания (корень {doc['root']}):",
           f"   субъектов {doc['subjects']} · приписано {doc['attributed']} · "
           f"перепись храповика {len(doc['census'])} · "
           f"ДВУСМЫСЛЕННЫХ {len(doc['ambiguous'])}"]
    if doc["ambiguous"]:
        for m in doc["ambiguous"]:
            row = next(r for r in doc["rows"] if r["module"] == m)
            g = row["grades"]
            out.append(f"     • {m} (стем {row['stem']}) — "
                       f"QUALIFIED {g[QUALIFIED]} · BARE {g[BARE]} · GLUED {g[GLUED]}"
                       f"{'' if row['stem_unique'] else ' · стем НЕ уникален'}")
            for p in (row["where"][GLUED] or row["where"][BARE])[:3]:
                out.append(f"         ← {p}")
    else:
        out.append("     ДВУСМЫСЛЕННЫХ 0 — это ЗАМЕР, а не молчание")
    out.append(f"   ось ПАР (стем A ⊂ имя субъекта B): пар {len(doc['pairs'])}, "
               f"субъектов в парах {len(doc['pair_members'])}, из них двусмысленных "
               f"{len(doc['pair_members_ambiguous'])}")
    out.append(f"   двусмысленных ВНЕ пар: {len(doc['ambiguous_outside_pairs'])} "
               f"{doc['ambiguous_outside_pairs'] or ''} — отношение «пара» классу "
               "ни достаточно, ни необходимо")
    share = doc["evidence_attributable_share"]
    out.append(
        "   КАЧЕСТВО доказательства (вопрос отдельный от вердикта): вхождений "
        f"{doc['evidence_total']} — QUALIFIED {doc['evidence'][QUALIFIED]} · "
        f"BARE {doc['evidence'][BARE]} · GLUED {doc['evidence'][GLUED]}; "
        + ("приписываемых "
           f"{share * 100:.1f} %" if share is not None
           else "НЕ ИЗМЕРЕНО: вхождений ноль"))
    out.append(
        f"   субъектов, у которых БОЛЬШИНСТВО вхождений не приписываемо: "
        f"{len(doc['majority_unattributable'])} из {doc['subjects']} — "
        "вердикт у них верен, а причина ему не принадлежит")
    out.append(f"   кандидатов ОМОНИМА базового имени: "
               f"{len(doc['homonym_candidates'])} {doc['homonym_candidates'] or ''}")
    out.append("   знак ошибки: признак ПРИПИСАНО щедрый ⇒ число есть ПОЛ класса, "
               "а не потолок")
    out.append("   ADVISORY: прибор только ЧИТАЕТ — ни один сторож, ни одна база, "
               "ни KNOWN_UNWIRED не изменены")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="дерево замера (умолчание — корень этого файла; ПЕЧАТАЕТСЯ)")
    ap.add_argument("--json", action="store_true", help="отдать документ на stdout")
    args = ap.parse_args(argv)
    try:
        doc = measure(pathlib.Path(args.root) if args.root else None)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print("\n".join(report(doc)))
    return 1 if doc["ambiguous"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
