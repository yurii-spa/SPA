"""Упоминание от того, кого САМОГО никто не зовёт, проводкой не является.

# LLM_FORBIDDEN

Храповик `test_unwired_guard_modules_ratchet` спрашивает ОДИН вопрос: встречается
ли стем модуля хоть в одном не-тестовом файле дерева. Вопрос верный и за три
ужесточения стал строже — проза (#255), комментарий (#227), текст сообщения
(#278), груз пуша (#379), путь тест-файла (ADR-835) проводкой больше не
считаются. Но у него осталась дверь, которую он не закрывает ПО ПОСТРОЕНИЮ:
он не спрашивает, зовёт ли кто-нибудь САМОГО упоминающего.

Замер #1163 (ADR-1025): список красного не удлинился (2 и 2), но СОСТАВ
сменился — `producer_input_awareness` ушёл из переписи только потому, что его
имя написал новый модуль, которого не зовёт никто. Это настоящий импорт, не
проза: ужесточения выше его не поймают и ловить не должны. Оттого и нужен
ОТДЕЛЬНЫЙ вопрос, а не ещё один стриппер.

Этот прибор его и задаёт — транзитивно, до неподвижной точки. Он ADVISORY:
своего вердикта в храповик не вносит, пока решение о храповике не принято
отдельно.

## Три исхода (инвариант #17)

* `REACHABLE` — субъекта упоминает файл, достижимый от объявленного корня;
* `ORPHAN_CHAIN` — depth-1 храповик числит субъекта подключённым, но все пути
  упоминаний умирают в субъектах, которых самих не зовёт никто. **Предмет класса.**
* `CENSUS` — субъект и так в переписи храповика (его не упоминает НИКТО).
  Не предмет этого класса: он уже на учёте.

«Не измерено» — ОТДЕЛЬНЫЙ исход, а не ноль: нечитаемый файл в поверхности
скана и тонкая поверхность поднимают `Unmeasured`, а CLI выходит кодом 2.

## Что объявлено КОРНЕМ — и почему это ПОЛ, а не потолок

Субъект — модуль с точкой входа в `spa_core/{alerts,monitoring,governance}`
(та же поверхность, что у храповика). **Корнем объявлен КАЖДЫЙ остальной файл
скана**: обёртка, plist, манифест, `scripts/**` и модуль-библиотека без точки
входа. Про их собственную достижимость этот прибор не спрашивает — у `scripts/`
на тот вопрос есть свой храповик (`test_unwired_scripts_ratchet`), а у
библиотек его нет вовсе.

Отсюда знак ошибки: объявление корнем может только ПРИБАВИТЬ достижимости,
значит найденное население — **ПОЛ класса, а не его потолок**. Утверждать по
этому числу «больше членов нет» запрещено.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
from typing import Dict, List, Optional, Set

from spa_core.tests import test_unwired_guard_modules_ratchet as _ratchet

#: Каталоги-поверхность субъектов — берутся у храповика, своей копии нет.
WATCHED_DIRS = _ratchet._DIRS

#: Где мог бы стоять вызов. Те же каталоги и суффиксы, что у храповика.
SCAN_SUBDIRS = ("spa_core", "scripts", "launchd", "architecture")
SCAN_SUFFIXES = (".py", ".sh", ".plist", ".json")

#: Пол непустоты поверхности. У храповика он 50 — тот же вопрос, то же число:
#: «сирот нет» не имеет права значить «скан ничего не нашёл».
MIN_SUBJECTS = 50

_ROOT = pathlib.Path(__file__).resolve().parents[2]

CENSUS = "CENSUS"
REACHABLE = "REACHABLE"
ORPHAN_CHAIN = "ORPHAN_CHAIN"


class Unmeasured(RuntimeError):
    """Поверхность не прочитана или тонка — это НЕ ноль находок."""


def tree_texts(root: pathlib.Path) -> Dict[str, str]:
    """{путь: текст} по поверхности скана — проза и пути тестов срезаны.

    Срезают их функции ХРАПОВИКА (`_code_only`, `_without_test_paths`): правило
    «что считается упоминанием» живёт в одном месте, и второй копии у него нет.
    Параметризован здесь только ОБХОД — храповик ходит от своего корня, а
    сценам прибора нужен одноразовый.

    Нечитаемый файл не пропускается молча: он и мог бы оказаться настоящим
    вызывающим, поэтому его имя уезжает наверх и делает замер `Unmeasured`.
    """
    out: Dict[str, str] = {}
    unreadable: List[str] = []
    for sub in SCAN_SUBDIRS:
        base = root / sub
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.suffix not in SCAN_SUFFIXES:
                continue
            rel = str(f.relative_to(root))
            if "/tests/" in rel or "/archive/" in rel:
                continue
            try:
                body = f.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                unreadable.append(f"{rel}: {exc}")
                continue
            out[rel] = _ratchet._without_test_paths(
                _ratchet._code_only(body) if f.suffix == ".py" else body)
    if unreadable:
        raise Unmeasured(
            "файлы поверхности скана не прочитаны, и любой из них мог быть "
            f"настоящим вызывающим: {unreadable}")
    return out


def subjects(root: pathlib.Path) -> List[str]:
    """Модули с точкой входа в наблюдаемых каталогах — поверхность храповика."""
    found: List[str] = []
    for sub in WATCHED_DIRS:
        d = root / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                body = f.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise Unmeasured(f"субъект не прочитан: {f} — {exc}") from exc
            if not _ratchet.has_entrypoint(body):
                continue
            found.append(str(f.relative_to(root)))
    return found


def measure(root: Optional[pathlib.Path] = None,
            min_subjects: int = MIN_SUBJECTS) -> dict:
    """Замер населения класса. Поднимает `Unmeasured`, если мерить нечем."""
    base = pathlib.Path(root) if root is not None else _ROOT
    base = base.resolve()
    subj = subjects(base)
    if len(subj) < min_subjects:
        raise Unmeasured(
            f"субъектов всего {len(subj)} при поле {min_subjects} — скан сузился, "
            "и «членов класса нет» значило бы «мерить было нечем»")
    texts = tree_texts(base)
    stem = {m: pathlib.Path(m).stem for m in subj}

    # Файл никогда не засчитывается сам себе — то же правило, что у храповика.
    mentioned_by = {m: sorted(p for p, body in texts.items()
                              if p != m and stem[m] in body) for m in subj}
    census = sorted(m for m in subj if not mentioned_by[m])

    # Корнем объявлен каждый файл скана, который не является субъектом.
    subj_set = set(subj)
    reach: Set[str] = {p for p in texts if p not in subj_set}
    rounds = 0
    changed = True
    while changed:
        changed = False
        rounds += 1
        for m in subj:
            if m in reach:
                continue
            if set(mentioned_by[m]) & reach:
                reach.add(m)
                changed = True

    status = {}
    for m in subj:
        if not mentioned_by[m]:
            status[m] = CENSUS
        elif m in reach:
            status[m] = REACHABLE
        else:
            status[m] = ORPHAN_CHAIN

    population = [
        {"module": m,
         "mentioned_by": [{"path": p, "status": status.get(p, "ROOT")}
                          for p in mentioned_by[m]]}
        for m in subj if status[m] == ORPHAN_CHAIN
    ]
    return {
        "measured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "root": str(base),
        "subjects": len(subj),
        "census_depth1": census,
        "deemed_wired_depth1": len(subj) - len(census),
        "reachable": sum(1 for m in subj if status[m] == REACHABLE),
        "orphan_chain": population,
        "fixpoint_rounds": rounds,
        "roots_declared": "каждый файл поверхности скана, не являющийся субъектом",
        "floor_not_ceiling": True,
        "status": status,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись класса «проводка упоминанием сироты» (ADVISORY)")
    ap.add_argument("--root", default=None,
                    help="дерево замера; умолчание ПЕЧАТАЕТСЯ")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-subjects", type=int, default=MIN_SUBJECTS,
                    help="пол непустоты поверхности; сдвиг ПЕЧАТАЕТСЯ")
    a = ap.parse_args(argv)
    if a.root is None:
        print(f"[дерево] умолчание: {_ROOT}", file=sys.stderr)
    if a.min_subjects != MIN_SUBJECTS:
        print(f"[пол] объявлен {a.min_subjects} вместо {MIN_SUBJECTS} — "
              "осознанный сдвиг", file=sys.stderr)
    try:
        rep = measure(pathlib.Path(a.root) if a.root else None,
                      min_subjects=a.min_subjects)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if rep["orphan_chain"] else 0
    print(f"дерево: {rep['root']}")
    print(f"субъектов (точка входа, {len(WATCHED_DIRS)} каталога): {rep['subjects']}")
    print(f"перепись храповика (не упоминает НИКТО): {len(rep['census_depth1'])}")
    print(f"числятся подключёнными depth-1: {rep['deemed_wired_depth1']}"
          f" · из них достижимы от корня: {rep['reachable']}")
    if not rep["orphan_chain"]:
        print("✅ население класса ПУСТО (это ПОЛ, а не потолок — см. докстроку)")
        return 0
    print(f"🔎 ПРОВОДКА УПОМИНАНИЕМ СИРОТЫ: {len(rep['orphan_chain'])}"
          f" (раундов фикспойнта {rep['fixpoint_rounds']})")
    for item in rep["orphan_chain"]:
        print(f"  • {item['module']}")
        for m in item["mentioned_by"]:
            print(f"      ← {m['path']} [{m['status']}]")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
