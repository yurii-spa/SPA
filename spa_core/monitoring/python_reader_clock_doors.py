"""Сколько питоньих читателей переписи держатся на дверях часов, связанных НА ИМПОРТЕ.

Заказ **G31 приказа владельца «Portfolio CIO»**, пункт 1 (поставлен ADR-405).

## Вопрос

ADR-401 провёл часы прогона в точку входа каждого читателя журнала решений, и
класс `verdict_rests_on_unstable_coords` у питоньей ветви обнулился. ADR-405
показал, что этого НЕ ДОСТАТОЧНО: у `decision_audit_trail` параметр `now=`
доходит до входа, а внутри `spa_core.audit.audit_trail._make_snapshot_id` зовёт
`datetime.now(timezone.utc)`, где имя `datetime` связано на импорте. Такую дверь
параметр не закрывает никогда — и молча: ответ плывёт, координата снимается как
нестабильная, читатель читается «нечувствителен к стенду».

Заказ велел СНАЧАЛА ЗАМЕРИТЬ, скольких читателей это касается, и лишь потом
платить за починку. Прибор отвечает ровно на этот вопрос — и ни на какой другой.

## Как меряется — по исходу, дифференциально

Два плеча, ОДИН стенд, ОДИН момент, по отдельному процессу на плечо:

* **A** — как перепись зовёт сегодня: `now=` в подпись, класс `datetime` настоящий;
* **B** — то же плюс подмена класса `datetime.datetime` ДО первого импорта `spa_core`.

Координата, нестабильная между двумя зовами в плече A и стабильная в плече B,
и есть дверь, связанная на импорте. Разность берётся ПОИМЁННО: счётчик одного
размера может получиться из разных множеств, и «столько же» не значит «те же».

Пин ПРОВЕРЯЕТСЯ ЗАМЕРОМ у двери (`pin_observed`), а не верой в переданный флаг:
плечо B, где пин не сработал, обязано быть НЕ ИЗМЕРЕНО, а не нулём дверей.

## Чего прибор НЕ докладывает

* Двери на `time.time()`: этот класс намеренно не закрепляется (TTL кешей и
  сроки ожидания превратились бы в вечный цикл — оговорка ADR-404). Ответ
  односторонний: «закрывается пином класса» либо «этим пином не закрывается».
* Верность самого ответа читателя. Прибор судит о ВОСПРОИЗВОДИМОСТИ, а не о
  правильности.
* Читатели, которых перепись не умеет привести (нет точки входа, импорт упал,
  вход упал) — они названы причинами, а не сосчитаны нулём.

Коды возврата: **0** — измерено, дверей нет · **1** — измерено, двери названы ·
**2** — НЕ ИЗМЕРЕНО (причина названа).

Прибор только ЧИТАЕТ. `POLLED_ADAPTERS`, писатель журнала, пороги RiskPolicy
v1.0, стоп-кран, живой трек и `landing/` не трогаются.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.monitoring import _python_reader_clock_probe as probe
from spa_core.utils.observation import observed
from spa_core.monitoring.run_identity_key_price import (
    build_stands, http_modules, reader_population,
)
from spa_core.utils.atomic import atomic_save

#: Корень дерева — три уровня вверх от ``spa_core/monitoring/<файл>``.
_ROOT = Path(__file__).resolve().parents[2]

#: Сколько ждать плечо. Плечо зовёт каждого приводимого читателя дважды.
ARM_TIMEOUT_S = 1800

ARTIFACT = "python_reader_clock_doors.json"

#: Имя прибора в отчёте — чтобы находку было с кем сверить.
PRODUCER = "spa_core/monitoring/python_reader_clock_doors.py"


def _self_modules() -> Tuple[str, ...]:
    """Модули, которых прибор не зовёт: он сам и перепись, которую он гоняет."""
    return ("spa_core.monitoring.run_identity_key_price",
            "spa_core.monitoring.python_reader_clock_doors",
            "spa_core.monitoring._python_reader_clock_probe",
            "spa_core.monitoring._http_reader_probe")


def population(tree_root: Path) -> Tuple[List[str], dict]:
    """Питоньи читатели: население переписи минус HTTP-ветвь и минус свои."""
    roads, stats = reader_population(tree_root)
    http = set(http_modules(sorted(roads)))
    skip = set(_self_modules())
    names = sorted(n for n in roads if n not in http and n not in skip)
    return names, {"population_total": len(roads),
                   "http_branch": len(http),
                   "python_branch": len(names),
                   "roads": stats}


def narrowed_population(names: List[str], census: Optional[dict]
                        ) -> Tuple[Optional[List[str]], dict]:
    """Только читатели, у которых перепись УЖЕ намерила нестабильные координаты.

    Читатель, у которого нестабильных координат НОЛЬ, двери, закрываемой пином,
    иметь не может — по определению самой меры (разность ``ua - ub`` пуста при
    пустом ``ua``). Поэтому сужение не теряет ни одного кандидата, а стоит на
    два порядка дешевле: полный прогон зовёт каждого из ста читателей дважды в
    каждом плече, среди них — соседние переписи, каждая ценой в минуты.

    Число берётся у ПЕРЕПИСИ (её же артефакт), но ОТВЕТ всё равно меряется здесь
    обоими плечами: сужение решает, кого спрашивать, а не что отвечать.

    Артефакта нет или он без строк ⇒ ``None`` и причина: это «не измерено», а
    не пустое население. Пустое население дало бы ноль дверей, и ноль читался бы
    как ответ.
    """
    if not census:
        return None, {"reason": "артефакта переписи нет — кого сужать, неизвестно"}
    rows = ((census.get("readers") or {}).get("modules") or [])
    if not rows:
        return None, {"reason": "в артефакте переписи нет строк читателей"}
    known = set(names)
    unstable = sorted(str(r.get("module")) for r in rows
                      if str(r.get("module")) in known
                      and int(r.get("unstable_coords") or 0) > 0)
    return unstable, {"mode": "narrowed_by_census",
                      "census_generated_at": census.get("generated_at"),
                      "census_rows": len(rows),
                      "with_unstable_coords": len(unstable),
                      "why": ("читатель без нестабильных координат не может иметь "
                              "двери, закрываемой пином — сужение кандидатов не теряет")}


def _load_census(data_dir: Path) -> Optional[dict]:
    """Артефакт переписи — единственный вход сужения. Не прочитан ⇒ ``None``."""
    try:
        return json.loads((Path(data_dir) / "run_identity_key_price.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_arm(names: List[str], stand: Path, tree_root: Path, moment: dt.datetime,
            *, pin: bool) -> Tuple[Optional[dict], str]:
    """Одно плечо — один процесс, зонд зовётся ПО ПУТИ.

    ``-m`` импортировал бы пакет ``spa_core.monitoring`` раньше, чем зонд успел
    бы что-нибудь закрепить, и плечо B стало бы копией плеча A.
    """
    script = Path(tree_root) / "spa_core" / "monitoring" / Path(probe.__file__).name
    with tempfile.TemporaryDirectory(prefix="spa_g31_arm_") as tmp:
        mods = Path(tmp) / "modules.json"
        out = Path(tmp) / "answer.json"
        mods.write_text(json.dumps(list(names)), encoding="utf-8")
        env = dict(os.environ)
        env[probe.STAND_ENV] = str(stand)
        env[probe.CLOCK_ENV] = moment.isoformat()
        env[probe.PIN_CLASS_ENV] = "1" if pin else "0"
        env["PYTHONPATH"] = os.pathsep.join(
            [str(tree_root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        try:
            proc = subprocess.run([sys.executable, str(script), str(mods), str(out)],
                                  cwd=str(tree_root), env=env, capture_output=True,
                                  timeout=ARM_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return None, f"плечо не уложилось в {ARM_TIMEOUT_S} с"
        if proc.returncode != 0 or not out.exists():
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
            return None, f"плечо вышло кодом {proc.returncode}: {tail}"
        try:
            return json.loads(out.read_text(encoding="utf-8")), ""
        except (OSError, ValueError) as exc:
            return None, f"ответ плеча не прочитан: {type(exc).__name__}"


def compare(arm_a: dict, arm_b: dict) -> dict:
    """Поимённая разность координат двух плеч.

    Три исхода у каждого читателя, и они РАЗЛИЧИМЫ (инв. #17):
    ``import_bound`` — координаты, закрытые пином класса;
    ``other_door`` — координаты, плывущие в ОБОИХ плечах (пином не закрываются);
    ``unmeasured`` — плечо не привело читателя, причина названа.
    """
    mods_a = arm_a.get("__modules__") or {}
    mods_b = arm_b.get("__modules__") or {}
    rows: Dict[str, dict] = {}
    for name in sorted(set(mods_a) | set(mods_b)):
        a, b = mods_a.get(name) or {}, mods_b.get(name) or {}
        if "unstable" not in a or "unstable" not in b:
            missing = a if "unstable" not in a else b
            rows[name] = {"outcome": "unmeasured",
                          "arm": "A" if "unstable" not in a else "B",
                          "cause": missing.get("cause") or "arm_silent",
                          "reason": missing.get("reason") or "плечо не дало ответа"}
            continue
        ua, ub = set(a["unstable"]), set(b["unstable"])
        row = {"outcome": "measured",
               "entry": a.get("entry"),
               "clock_injected": a.get("clock_injected"),
               "import_bound": sorted(ua - ub),
               "other_door": sorted(ua & ub),
               # Обратная сторона обязана быть НАЗВАНА, а не молча отброшена:
               # координата, ставшая нестабильной ОТ ПИНА, означала бы, что
               # мера шумит, и находку в такой паре предъявлять нельзя.
               "unstable_only_pinned": sorted(ub - ua)}
        rows[name] = row
    return rows


def measure(data_dir: Path, tree_root: Path, *,
            now: Optional[dt.datetime] = None, full: bool = False) -> dict:
    """Замер целиком. Стенд строится на КОПИИ ``data/``, живой каталог не трогается."""
    moment = now or dt.datetime.now(dt.timezone.utc)
    doc: Dict[str, object] = {
        "generated_at": moment.isoformat(),
        "generated_by": PRODUCER,
        "question": ("сколько питоньих читателей переписи держатся на дверях часов, "
                     "связанных НА ИМПОРТЕ (заказ G31 приказа «Portfolio CIO», п. 1)"),
        "what_it_does_not_prove": [
            "двери на time.time(): этот класс намеренно не закрепляется (TTL и ожидания)",
            "верность ответа читателя — мерится ВОСПРОИЗВОДИМОСТЬ, не правильность",
            "читатели, которых перепись не умеет привести, названы причинами, не нулём",
        ],
        "advisory": ("POLLED_ADAPTERS, писатель журнала, audit_trail, пороги RiskPolicy "
                     "v1.0, стоп-кран, живой трек и landing/ НЕ трогаются — прибор только "
                     "ЧИТАЕТ и называет, какие координаты закрываются пином класса часов"),
    }
    names, pop = population(tree_root)
    if not full:
        narrowed, why = narrowed_population(names, _load_census(data_dir))
        if narrowed is None:
            doc["population"] = pop
            doc.update(status="UNMEASURED", reason=f"сужение не построено: {why['reason']}")
            return doc
        pop.update(why)
        names = narrowed
    else:
        pop["mode"] = "full_population"
    doc["population"] = pop
    with tempfile.TemporaryDirectory(prefix="spa_g31_stand_") as tmp:
        stands, why = build_stands(Path(data_dir), Path(tmp))
        if stands is None:
            doc.update(status="UNMEASURED", reason=f"стенд не построен: {why}")
            return doc
        doc["stand"] = {"day": stands["day"], "donor_day": stands["donor_day"]}
        arm_a, why_a = run_arm(names, stands["s1"], tree_root, moment, pin=False)
        if arm_a is None:
            doc.update(status="UNMEASURED", reason=f"плечо A: {why_a}")
            return doc
        arm_b, why_b = run_arm(names, stands["s1"], tree_root, moment, pin=True)
        if arm_b is None:
            doc.update(status="UNMEASURED", reason=f"плечо B: {why_b}")
            return doc
    clock_a = arm_a.get("__clock__") or {}
    clock_b = arm_b.get("__clock__") or {}
    doc["arms"] = {"A": clock_a, "B": clock_b}
    # Плечи обязаны ОТЛИЧАТЬСЯ пином, и это ЗАМЕР у двери, а не флаг. Плечо B
    # без наблюдённого пина даёт нулевую разность, и ноль этот — «нечем было
    # мерить», а не «дверей нет»: fail-OPEN тише красной строки.
    if not clock_b.get("pin_observed"):
        doc.update(status="UNMEASURED",
                   reason="в плече B пин класса часов НЕ НАБЛЮДЁН у двери — "
                          "разность плеч была бы ответом о приборе, а не о читателях")
        return doc
    if clock_a.get("pin_observed"):
        doc.update(status="UNMEASURED",
                   reason="в плече A часы оказались закреплены — плечи неразличимы, "
                          "мерить нечем")
        return doc
    rows = compare(arm_a, arm_b)
    doc["modules"] = rows
    measured = {n: r for n, r in rows.items() if r["outcome"] == "measured"}
    doors = {n: r["import_bound"] for n, r in measured.items() if r["import_bound"]}
    noisy = {n: r["unstable_only_pinned"] for n, r in measured.items()
             if r["unstable_only_pinned"]}
    other = {n: r["other_door"] for n, r in measured.items() if r["other_door"]}
    doc["counts"] = {
        "python_branch": len(names),
        "measured": len(measured),
        "unmeasured": len(rows) - len(measured),
        "rest_on_import_bound_door": len(doors),
        "rest_on_other_door": len(other),
        "noisy_reverse": len(noisy),
    }
    doc["import_bound_doors"] = doors
    doc["other_doors"] = other
    doc["reverse_direction"] = noisy
    doc["unmeasured_causes"] = _causes(rows)
    doc["status"] = "FINDING" if doors else "OK"
    return doc


def _causes(rows: Dict[str, dict]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for row in rows.values():
        if row["outcome"] != "unmeasured":
            continue
        key = str(row.get("cause") or "cause_not_recorded")
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _num(counts: dict, key: str) -> str:
    """Число счётчика — или НАЗВАННОЕ «не измерено», но никогда `None` в тексте.

    Инвариант #17 действует и на печать: `None`, попавший в предложение отчёта,
    читается как значение («вышло ничего»), а не как «мерить было нечем».
    """
    value = observed(counts, key, kind=(int, float))
    return "НЕ ИЗМЕРЕНО" if value is None else str(value)


def report(doc: dict) -> List[str]:
    lines = [f"двери часов, связанные на импорте, у питоньих читателей переписи "
             f"(заказ G31 п. 1): {doc.get('status')}"]
    if doc.get("status") == "UNMEASURED":
        lines.append(f"   [НЕ ИЗМЕРЕНО] {doc.get('reason')}")
        return lines
    counts = observed(doc, "counts", kind=dict)
    if counts is None:
        # Инвариант #17. Прежде здесь стояло `doc.get("counts") or {}`, и
        # артефакт БЕЗ раздела счётчиков печатался как ответ, в котором все
        # числа — `None`: «измерено и вышло ничего» было неотличимо от «мерить
        # было нечем». Строка ответа — главная в отчёте, и предъявлять её
        # пустой значит предъявлять находку, которой нет.
        lines.append("   [НЕ ИЗМЕРЕНО] раздела `counts` в артефакте нет — чисел "
                     "ответа назвать нечем; строки ниже описывают ЧАСТЬ, а не итог")
    else:
        lines.append(
            f"   [ОТВЕТ] из {_num(counts, 'measured')} приведённых читателей "
            f"(население питоньей ветви {_num(counts, 'python_branch')}) на дверях, "
            f"СВЯЗАННЫХ НА ИМПОРТЕ, держатся "
            f"**{_num(counts, 'rest_on_import_bound_door')}**; "
            f"на дверях, которые пином класса НЕ закрываются — "
            f"{_num(counts, 'rest_on_other_door')}; не приведено "
            f"{_num(counts, 'unmeasured')}")
    for name, coords in sorted((doc.get("import_bound_doors") or {}).items()):
        lines.append(f"   [ПИН ЗАКРЫВАЕТ] {name}: {', '.join(coords[:6])}"
                     + (f" … и ещё {len(coords) - 6}" if len(coords) > 6 else ""))
    for name, coords in sorted((doc.get("other_doors") or {}).items()):
        lines.append(f"   [ПИН НЕ ЗАКРЫВАЕТ] {name}: {', '.join(coords[:6])}"
                     + (f" … и ещё {len(coords) - 6}" if len(coords) > 6 else ""))
    reverse = doc.get("reverse_direction") or {}
    if reverse:
        lines.append(f"   [ОБРАТНАЯ СТОРОНА] у {len(reverse)} читател(я/ей) координата "
                     f"стала нестабильной ОТ ПИНА — мера шумит на этих парах, "
                     f"находку по ним предъявлять нельзя: {', '.join(sorted(reverse))}")
    else:
        lines.append("   [ОПОРА] обратной стороны нет: ни у одного читателя пин не "
                     "СОЗДАЛ нестабильной координаты — разность односторонняя")
    causes = observed(doc, "unmeasured_causes", kind=dict)
    if causes is None:
        # Третий исход, которого здесь не было: раздела причин НЕТ в артефакте.
        # Прежде `or {}` сливал его с пустым разбором, и обе беды молчали
        # ОДИНАКОВО — то есть отсутствие разбора читалось как «непривёденных
        # читателей нет», самый тихий вид fail-OPEN.
        lines.append("   [НЕ ИЗМЕРЕНО] разбора причин в артефакте нет — у числа "
                     "«не приведено» поимённого состава не существует")
    elif causes:
        lines.append("   [НЕ ИЗМЕРЕНО поимённо] "
                     + " · ".join(f"{k}: {v}" for k, v in causes.items()))
    else:
        lines.append("   [ОПОРА] разбор причин ПУСТ: не приведённых читателей нет, "
                     "называть нечего — это замер, а не пропажа")
    lines.append("   ADVISORY: " + str(doc.get("advisory")))
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="двери часов, связанные на импорте, у питоньих читателей переписи")
    ap.add_argument("--data-dir", default=str(_ROOT / "data"),
                    help="каталог data/, с которого строится стенд (КОПИЯ, не правится)")
    ap.add_argument("--tree-root", default=str(_ROOT))
    ap.add_argument("--out", default=None,
                    help="куда положить артефакт (по умолчанию <data-dir>/"
                         + ARTIFACT + ")")
    ap.add_argument("--full", action="store_true",
                    help="звать ВСЁ население питоньей ветви, а не только читателей "
                         "с нестабильными координатами (дороже на два порядка)")
    ap.add_argument("--no-write", action="store_true",
                    help="не писать артефакт — только напечатать отчёт")
    args = ap.parse_args(argv)

    doc = measure(Path(args.data_dir), Path(args.tree_root), full=args.full)
    for line in report(doc):
        print(line)
    if not args.no_write:
        dest = Path(args.out) if args.out else Path(args.data_dir) / ARTIFACT
        atomic_save(doc, str(dest))
    return {"UNMEASURED": 2, "FINDING": 1}.get(str(doc.get("status")), 0)


if __name__ == "__main__":
    raise SystemExit(main())
