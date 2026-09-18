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

## Цена закрытия двери (заказ G32, п. 1)

Сосчитать двери мало: заказ велел измерить, во что обходится закрытие КАЖДОЙ,
и лишь потом выбирать. Цена измерима тем же дифференциальным способом, только
вопрос другой — не «где дрожит», а **изменился ли сам ОТВЕТ читателя**.
Сравниваются значения координат, стабильных в ОБОИХ плечах: разошлись ⇒ пин не
снял дрожь, а переписал вердикт.

Это не теория. У `decision_audit_trail` дрожь координат
`.snapshot_id_probe.samples[0..1]` есть НЕ помеха замеру, а сам замер: читатель
нарочно зовёт производителя дважды и по совпадению ответов судит, адресует ли
`snapshot_id` содержимое. Под пином ответы совпадают всегда, и вердикт
переворачивается на противоположный — то есть закрытие этой двери ПОДДЕЛЫВАЕТ
находку. Дверей три, но закрывать можно не три.

Плечей поэтому ТРИ: **A′** — точная копия A без пина. Плечи суть разные
процессы, и координата может отличаться между ними сама по себе (номер
процесса, путь временного стенда); приписать такую разницу пину значило бы
выдумать находку. Что расходится уже между A и A′, то расходится не от пина.
Контрольного плеча нет ⇒ цена **НЕ ИЗМЕРЕНА**, а не «нулевая».

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
from spa_core.monitoring.call_provenance import call_provenance
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

#: Такт переизмерения, дней. Заказ **G33, п. 2**: артефакта на прод-пути не было
#: ВОВСЕ (замер #623), а «считать заодно внутри дневной переписи» отпало — чистый
#: замер #625 ниже назвал цену прогона, и она в десятках минут. Такт назначен
#: недельным по той же причине, по которой он недельный у витрины чисел сайта:
#: предмет (двери в КОДЕ) меняется доставками, а не календарём, и переизмерять
#: его каждый день значило бы платить десятки минут за ответ, который почти
#: всегда тот же. Срок решает ФАЙЛ, а не расписание запуска — иначе «раз в
#: неделю» держалось бы на том, что никто не трогал cron.
MEASUREMENT_TACT_DAYS = 7

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


def answer_shift(arm_a_row: dict, arm_b_row: dict,
                 arm_a2_row: Optional[dict]) -> dict:
    """Изменил ли пин сам ОТВЕТ читателя — и отделён ли сдвиг от шума процессов.

    Разность ИМЁН нестабильных координат отвечает только на вопрос «где дрожит».
    Заказ G32 п. 1 требует другого: **цены** закрытия каждой двери. Цена тут
    измерима по исходу — сравнить значения координат, стабильных в ОБОИХ плечах.
    Разошлись ⇒ пин не снял дрожь, а переписал вердикт.

    Почему нужен КОНТРОЛЬ, а не прямая разность A↔B. Плечи — разные процессы, и
    координата может отличаться между ними сама по себе (номер процесса, путь
    временного стенда, порядок обхода множества). Приписать такую разницу пину
    значило бы выдумать находку. Поэтому третье плечо **A′** — точная копия A,
    без пина: что расходится уже между A и A′, то расходится не от пина.

    Три исхода, и они различимы (инв. #17):
    ``measured`` со списками ``by_pin`` / ``process_varying``;
    ``unmeasured`` — плечо не вернуло значений либо контрольного плеча нет:
    цену назвать нечем, и это НЕ «цена нулевая».
    """
    sa = arm_a_row.get("stable")
    sb = arm_b_row.get("stable")
    if not isinstance(sa, dict) or not isinstance(sb, dict):
        which = "A" if not isinstance(sa, dict) else "B"
        return {"outcome": "unmeasured",
                "reason": (f"плечо {which} не вернуло значений стабильных координат — "
                           "цену закрытия двери назвать нечем")}
    s2 = arm_a2_row.get("stable") if isinstance(arm_a2_row, dict) else None
    if not isinstance(s2, dict):
        return {"outcome": "unmeasured",
                "reason": ("контрольного плеча A′ нет — отличить сдвиг ОТ ПИНА от "
                           "разницы двух процессов нечем")}
    noise = {c for c in (set(sa) & set(s2)) if sa[c]["digest"] != s2[c]["digest"]}
    differ = [c for c in sorted(set(sa) & set(sb))
              if sa[c]["digest"] != sb[c]["digest"]]
    by_pin = [c for c in differ if c not in noise]
    return {"outcome": "measured",
            "by_pin": by_pin,
            # Обе стороны названы: шум процессов не есть находка, но и молча
            # выброшенным он быть не должен — иначе разность «A↔B минус шум»
            # выглядела бы прямым замером, каким она не является.
            "process_varying": sorted(noise),
            "samples": {c: {"unpinned": sa[c]["preview"], "pinned": sb[c]["preview"]}
                        for c in by_pin[:8]}}


#: Временный каталог процесса. Плечи наследуют окружение прибора, поэтому
#: ``TMPDIR`` у них тот же — сравнение идёт с одним и тем же корнем.
_TMP_ROOT = os.path.realpath(tempfile.gettempdir())


def _under_tmp(value: str) -> bool:
    try:
        real = os.path.realpath(value)
    except (OSError, ValueError):                      # pragma: no cover
        return False
    return real == _TMP_ROOT or real.startswith(_TMP_ROOT + os.sep)


def own_temp_stand(arm_row: dict, coord: str) -> Optional[bool]:
    """Несёт ли плывущая координата СВОЙ временный стенд читателя — ЗАМЕРОМ.

    Заказ **G33, п. 4**. `heir_all_rows_price` и `judge_alone_price` строят себе
    стенд (`tempfile.mkdtemp`, свежий на каждый зов) и кладут его путь в ответ —
    нарочно, как ответ на вопрос «против чего меряно». Метка «пин этого не
    закрывает» на такой координате формально верна, но читается как «дверь, к
    которой нужен другой ключ», а двери там нет вовсе.

    Различать этот класс по ИМЕНИ координаты (`.stand_root`, `.stand.s_*`) было
    бы догадкой и ошибалось бы в обе стороны: имя `stand_root` может однажды
    нести настроечный путь из файла, а свой стенд может уехать в координату с
    любым другим именем. Поэтому судит замер: **два РАЗНЫХ абсолютных пути под
    временным каталогом на двух зовах одного стенда** — это и есть «читатель
    завёл себе каталог заново», и никакое закрытие дверей часов на это не
    влияет.

    Три исхода, различимые (инв. #17): ``True`` — измерено, свой стенд;
    ``False`` — измерено, не стенд; ``None`` — НЕ ИЗМЕРЕНО (значений нет, или
    координата вообще не лист ответа). ``None`` никогда не выдаётся за ``False``:
    иначе «мерить было нечем» слилось бы с «проверено, это дверь».
    """
    values = observed(arm_row, "unstable_values", kind=dict)
    if values is None:
        return None
    first = observed(values, "first", kind=dict)
    second = observed(values, "second", kind=dict)
    if first is None or second is None:
        return None
    side_a, side_b = first.get(coord), second.get(coord)
    if not isinstance(side_a, dict) or not isinstance(side_b, dict):
        return None
    if "not_a_string" in side_a and "not_a_string" in side_b:
        return False                       # лист есть, он не строка — не путь
    if "value" not in side_a or "value" not in side_b:
        return None                        # координата не лист ⇒ не измерено
    one, two = side_a["value"], side_b["value"]
    if one == two or not os.path.isabs(one) or not os.path.isabs(two):
        return False
    return _under_tmp(one) and _under_tmp(two)


def split_provenance(row: dict, arm_a_row: dict) -> Tuple[List[str], List[str],
                                                          Dict[str, str]]:
    """Плывущие-в-обоих-плечах координаты → дверь · провенанс прогона · не измерено.

    Из ``other_door`` уходит только то, про что замер сказал **да**. Координата,
    про которую замер сказать не смог, из ведра НЕ вынимается: утверждение «пин
    её не закрывает» про неё по-прежнему верно и измерено — не измерено ЛИШЬ
    более сильное утверждение «и это настоящая дверь, а не свой стенд». Вынести
    её отсюда значило бы молча опустошить ответ на старый вопрос ради нового —
    fail-OPEN тише красной строки. Поэтому она остаётся в дверях И называется
    вслух в ``provenance_unmeasured``.
    """
    doors: List[str] = []
    provenance: List[str] = []
    unmeasured: Dict[str, str] = {}
    for coord in row.get("other_door") or []:
        verdict = own_temp_stand(arm_a_row, coord)
        if verdict:
            provenance.append(coord)
            continue
        doors.append(coord)
        if verdict is None:
            unmeasured[coord] = ("значений этой координаты плечо A не вернуло — "
                                 "свой временный стенд от настоящей двери "
                                 "отличить было нечем")
    return doors, provenance, unmeasured


def compare(arm_a: dict, arm_b: dict, arm_a2: Optional[dict] = None) -> dict:
    """Поимённая разность координат двух плеч плюс цена закрытия двери.

    Три исхода у каждого читателя, и они РАЗЛИЧИМЫ (инв. #17):
    ``import_bound`` — координаты, закрытые пином класса;
    ``other_door`` — координаты, плывущие в ОБОИХ плечах (пином не закрываются);
    ``unmeasured`` — плечо не привело читателя, причина названа.

    Плюс у каждого приведённого читателя — ``answer_shift`` (см. соседа):
    ЦЕНА пина, то есть изменил ли он вердикт читателя, а не только его дрожь.
    """
    mods_a = arm_a.get("__modules__") or {}
    mods_b = arm_b.get("__modules__") or {}
    mods_a2 = (arm_a2 or {}).get("__modules__") or {}
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
        row["answer_shift"] = answer_shift(a, b, mods_a2.get(name))
        # Заказ G33 п. 4: «пин не закрывает» — не один класс, а три. Отделяется
        # ЗАМЕРОМ (см. `own_temp_stand`), и неизмеримое остаётся неизмеренным,
        # а не спускается в «дверь».
        doors, provenance, unmeasured = split_provenance(row, a)
        row["other_door"] = doors
        row["run_provenance"] = provenance
        row["provenance_unmeasured"] = unmeasured
        rows[name] = row
    return rows


def measure(data_dir: Path, tree_root: Path, *,
            now: Optional[dt.datetime] = None, full: bool = False) -> dict:
    """Замер целиком. Стенд строится на КОПИИ ``data/``, живой каталог не трогается."""
    moment = now or dt.datetime.now(dt.timezone.utc)
    doc: Dict[str, object] = {
        "generated_at": moment.isoformat(),
        # `generated_by` — КОНСТАНТА с именем этого модуля: она отвечает «чем
        # написано», и ответ у неё один при любом зове. Заказ G36 п. 1 спрашивает
        # ДРУГОЕ — «кем позвано», и до этой строки такого поля не было ни у одного
        # из двух сравниваемых приборов, отчего само сравнение 25.09 было
        # неизмеримо (ADR-412).
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=Path(tree_root)),
        "question": ("сколько питоньих читателей переписи держатся на дверях часов, "
                     "связанных НА ИМПОРТЕ (заказ G31 приказа «Portfolio CIO», п. 1) "
                     "и во что обходится закрытие каждой такой двери (заказ G32, п. 1)"),
        "what_it_does_not_prove": [
            "двери на time.time(): этот класс намеренно не закрепляется (TTL и ожидания)",
            "верность ответа читателя — мерится ВОСПРОИЗВОДИМОСТЬ, не правильность",
            "читатели, которых перепись не умеет привести, названы причинами, не нулём",
            "НУЖНА ли дверь закрытию: прибор меряет ЦЕНУ закрытия, а не пользу от него",
            "координата теперь ЛИЧНОСТНА там, где личность измерима "
            "(`.findings[code=…]`, заказ G33 п. 3), но НЕ везде: у списка, чьи "
            "элементы не называют себя уникальным скалярным полем, запись "
            "остаётся позиционной — и там прежняя оговорка #624 в силе "
            "(исчезновение элемента сдвигает индексы соседей)",
            "«свой временный стенд» (заказ G33 п. 4) устанавливается ОДНОСТОРОННЕ: "
            "два разных абсолютных пути под временным каталогом — это стенд, "
            "обратное же не доказано: из `other_doors` вынимается ТОЛЬКО то, про "
            "что замер сказал «да»; и не прошедшая признак, и неизмеримая "
            "остаются дверьми — вторая вдобавок названа в "
            "`provenance_unmeasured`, потому что «пин её не закрывает» измерено, "
            "а «это настоящая дверь» — нет",
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
        # Плечо A′ — точная копия A, без пина. Контроль на шум процессов: без
        # него разность A↔B в значениях приписала бы пину всё, что отличает два
        # процесса вообще, и цена закрытия двери была бы выдумкой.
        arm_a2, why_a2 = run_arm(names, stands["s1"], tree_root, moment, pin=False)
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
    if arm_a2 is None:
        # Не отказ всего замера: разность ИМЁН (двери) измерима и без контроля.
        # Отказывает ровно тот вопрос, у которого пропала посылка, — ЦЕНА.
        doc["control_arm"] = {"outcome": "unmeasured", "reason": f"плечо A′: {why_a2}"}
    else:
        doc["control_arm"] = {"outcome": "measured",
                              "pin_observed": (arm_a2.get("__clock__") or {}).get(
                                  "pin_observed")}
        if (arm_a2.get("__clock__") or {}).get("pin_observed"):
            # A′ обязано быть НЕ закреплено: закреплённый контроль объявил бы
            # шумом ровно то, что ищет прибор, — и находка исчезла бы молча.
            doc["control_arm"] = {"outcome": "unmeasured",
                                  "reason": "в контрольном плече A′ часы оказались "
                                            "закреплены — оно неотличимо от B и "
                                            "объявило бы шумом сам сдвиг от пина"}
            arm_a2 = None
    rows = compare(arm_a, arm_b, arm_a2)
    doc["modules"] = rows
    measured = {n: r for n, r in rows.items() if r["outcome"] == "measured"}
    doors = {n: r["import_bound"] for n, r in measured.items() if r["import_bound"]}
    noisy = {n: r["unstable_only_pinned"] for n, r in measured.items()
             if r["unstable_only_pinned"]}
    other = {n: r["other_door"] for n, r in measured.items() if r["other_door"]}
    provenance = {n: r["run_provenance"] for n, r in measured.items()
                  if r.get("run_provenance")}
    prov_unmeasured = {n: r["provenance_unmeasured"] for n, r in measured.items()
                       if r.get("provenance_unmeasured")}
    # ЦЕНА закрытия каждой двери — заказ G32, п. 1. Три исхода, различимые:
    # бесплатно · закрытие переписывает ответ читателя · цена не измерена.
    free: Dict[str, list] = {}
    falsifying: Dict[str, dict] = {}
    price_unmeasured: Dict[str, str] = {}
    for name in sorted(doors):
        shift = measured[name].get("answer_shift") or {}
        if shift.get("outcome") != "measured":
            price_unmeasured[name] = str(shift.get("reason") or "цена не измерена")
        elif shift.get("by_pin"):
            # Инв. #17 и на превью: «раздела значений нет» обязано отличаться
            # от «значения есть и их ноль», иначе отчёт назовёт координату
            # изменившейся, не показав НИ ОДНОГО значения, и это прочтётся
            # как «изменение пустое».
            falsifying[name] = {"door": doors[name],
                                "answer_changed_at": shift["by_pin"],
                                "samples": observed(shift, "samples", kind=dict)}
        else:
            free[name] = doors[name]
    doc["counts"] = {
        "python_branch": len(names),
        "measured": len(measured),
        "unmeasured": len(rows) - len(measured),
        "rest_on_import_bound_door": len(doors),
        "rest_on_other_door": len(other),
        "carry_run_provenance_not_a_door": len(provenance),
        "provenance_unmeasured": len(prov_unmeasured),
        "noisy_reverse": len(noisy),
        "doors_free_to_close": len(free),
        "doors_whose_closing_rewrites_the_answer": len(falsifying),
        "door_price_unmeasured": len(price_unmeasured),
    }
    doc["import_bound_doors"] = doors
    doc["doors_free_to_close"] = free
    doc["doors_that_rewrite_the_answer"] = falsifying
    doc["door_price_unmeasured"] = price_unmeasured
    doc["other_doors"] = other
    doc["run_provenance"] = provenance
    doc["provenance_unmeasured"] = prov_unmeasured
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
    # Заказ G33 п. 4. Раздела нет ⇒ так и сказать: «двери там нет» и «мы не
    # смотрели» — разные утверждения, и второе не имеет права молчать.
    provenance = observed(doc, "run_provenance", kind=dict)
    prov_unmeasured = observed(doc, "provenance_unmeasured", kind=dict)
    if provenance is None or prov_unmeasured is None:
        lines.append("   [НЕ ИЗМЕРЕНО] разбора «дверь или провенанс прогона» в "
                     "артефакте нет — координаты, которые пин не закрывает, "
                     "предъявлены одним ведром")
    else:
        for name, coords in sorted(provenance.items()):
            lines.append(
                f"   [НЕ ДВЕРЬ, А ПРОВЕНАНС ПРОГОНА] {name}: "
                f"{', '.join(coords[:6])}"
                + (f" … и ещё {len(coords) - 6}" if len(coords) > 6 else "")
                + " — замером: два РАЗНЫХ абсолютных пути под временным "
                  "каталогом на двух зовах, то есть читатель заводит себе стенд "
                  "заново; закрывать тут нечего")
        for name, coords in sorted(prov_unmeasured.items()):
            lines.append(
                f"   [НЕ ИЗМЕРЕНО: дверь или свой стенд] {name}: "
                + " · ".join(f"{c} — {r}" for c, r in sorted(coords.items()))
                + "; эти координаты ОСТАЛИСЬ в строке «пин не закрывает» — то "
                  "утверждение измерено, не измерено лишь более сильное")
    # ЦЕНА закрытия — раздел заказа G32 п. 1. Инв. #17: «раздела нет» обязано
    # звучать иначе, чем «цена нулевая», иначе молчание читается как разрешение.
    price = observed(doc, "doors_that_rewrite_the_answer", kind=dict)
    free = observed(doc, "doors_free_to_close", kind=dict)
    unpriced = observed(doc, "door_price_unmeasured", kind=dict)
    if price is None or free is None or unpriced is None:
        lines.append("   [НЕ ИЗМЕРЕНО] цены закрытия дверей в артефакте нет — какая "
                     "дверь закрывается даром, а какая перепишет ответ читателя, "
                     "сказать нечем")
    else:
        for name, row in sorted(price.items()):
            changed = ", ".join(row.get("answer_changed_at") or [])
            lines.append(
                f"   [ЗАКРЫТИЕ ПЕРЕПИШЕТ ОТВЕТ] {name}: дверь "
                f"{', '.join(row.get('door') or [])} — но тот же пин меняет ВЕРДИКТ "
                f"читателя в {changed}; дрожь тут не шум, а измеряемое свойство, и "
                f"закрыть дверь значит подделать находку")
            previews = observed(row, "samples", kind=dict)
            if previews is None:
                lines.append("      · [НЕ ИЗМЕРЕНО] значений этих координат в "
                             "артефакте нет — ЧТО именно изменилось, не показано")
            elif not previews:
                lines.append("      · значений не приложено: список изменившихся "
                             "координат пуст либо обрезан до нуля")
            for coord, pair in sorted((previews if previews else {}).items()):
                lines.append(f"      · {coord}: без пина {pair.get('unpinned')} → "
                             f"с пином {pair.get('pinned')}")
        if free:
            lines.append("   [ЗАКРЫТИЕ ДАРОМ] "
                         + " · ".join(f"{n}: {', '.join(c)}" for n, c in sorted(free.items())))
        if unpriced:
            lines.append("   [ЦЕНА НЕ ИЗМЕРЕНА] "
                         + " · ".join(f"{n}: {r}" for n, r in sorted(unpriced.items())))
        if not price and not unpriced and free:
            lines.append("   [ОПОРА] ни у одной двери закрытие не переписывает ответ "
                         "читателя — цена измерена и нулевая у всех")
    control = doc.get("control_arm") or {}
    if control.get("outcome") != "measured":
        lines.append(f"   [НЕ ИЗМЕРЕНО] контрольное плечо A′: "
                     f"{control.get('reason', 'плеча нет')} — разницу двух процессов "
                     f"от сдвига ОТ ПИНА отделить было нечем")
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


def measurement_due(out: Path, *, now: Optional[dt.datetime] = None,
                    tact_days: int = MEASUREMENT_TACT_DAYS) -> Tuple[bool, str]:
    """Пора ли переизмерять — решает ФАЙЛ, а не расписание запуска.

    Заказ **G33, п. 2**. Три исхода, и они различимы (инв. #17): артефакта нет
    ⇒ **пора** (первый замер — ровно состояние, найденное #623 на прод-пути);
    отметка не разобрана ⇒ тоже **пора**, потому что «не смогли прочитать, когда
    мерили» не имеет права означать «мерили недавно» — это подстановка молчания
    на место наблюдения; отметка свежее такта ⇒ **не пора**, и это ЗАМЕР, а не
    отказ.
    """
    moment = now if now is not None else dt.datetime.now(dt.timezone.utc)
    if not Path(out).is_file():
        return True, "артефакта нет — первый замер"
    try:
        raw = json.loads(Path(out).read_text(encoding="utf-8")).get("generated_at")
        last = dt.datetime.fromisoformat(str(raw))
    except (OSError, ValueError, TypeError) as exc:
        return True, f"отметка прошлого замера не прочитана ({type(exc).__name__}) — мерим"
    if last.tzinfo is None:
        return True, "отметка прошлого замера без пояса — мерим"
    age_days = (moment - last).total_seconds() / 86400.0
    if age_days >= tact_days:
        return True, (f"со дня замера {last.isoformat()} прошло "
                      f"{age_days:.1f} дн (такт {tact_days})")
    return False, (f"со дня замера {last.isoformat()} прошло {age_days:.1f} дн "
                   f"из {tact_days}")


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
    ap.add_argument("--if-due", action="store_true",
                    help=f"мерить, только если со дня прошлого замера прошло "
                         f"{MEASUREMENT_TACT_DAYS} дн (прогон стоит десятки минут)")
    args = ap.parse_args(argv)

    dest = (Path(args.out) if args.out
            else Path(args.data_dir) / ARTIFACT)
    if args.if_due:
        due, why = measurement_due(dest)
        if not due:
            print(f"замер не назначен: {why}")
            return 0
    doc = measure(Path(args.data_dir), Path(args.tree_root), full=args.full)
    for line in report(doc):
        print(line)
    if not args.no_write:
        atomic_save(doc, str(dest))
    return {"UNMEASURED": 2, "FINDING": 1}.get(str(doc.get("status")), 0)


if __name__ == "__main__":
    raise SystemExit(main())
