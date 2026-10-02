"""Перепись списков БЕЗ личности в ответах питоньих читателей.

Заказ **G34, п. 1** приказа владельца «Portfolio CIO» (хвост ADR-409).

## Вопрос, на который прибор отвечает

`element_identity` (ADR-409, `run_identity_key_price`) выбирает поле, которым
элементы списка называют СЕБЯ, и имеет три исхода. Третий — «годного поля нет»
— честно оставляет обход позиционным: координата вида ``.findings[8].severity``
заговорит о ДРУГОЙ находке, стоит набору сменить длину, не изменив ни буквы в
своём имени. Заказ спрашивает ЗАМЕР, а не догадку:

1. сколько списков в ответах читателей попадают СЕЙЧАС в третий исход;
2. у скольких из них есть **годное** поле-кандидат, которого нет в
   ``_IDENTITY_FIELDS``.

Второе число и есть цена нынешнего списка имён: список назван на глаз, и
дописывать в него имена дальше на глаз — ровно та догадка, против которой
написан сам приём. Перепись превращает «кажется, надо добавить `label`» в
«`label` годен у N списков из M, и вот они поимённо».

## Чего перепись НЕ доказывает

* **Годность ≠ верность.** Поле, уникальное на сегодняшнем ответе, завтра может
  повториться. Прибор меряет СОСТАВ одного наблюдённого ответа, а не обещание
  писателя; поэтому вывод односторонний: «годного поля нет» — свойство, «поле
  годно» — наблюдение.
* **Список из ОДНОГО элемента годен тривиально**: любое скалярное поле в нём
  уникально по построению — это совпадение, а не свойство (тот же довод, по
  которому `element_identity` исключает ``bool``). Поэтому синглтоны считаются
  ОТДЕЛЬНО и в число-находку не входят.
* Читатель, которого нельзя позвать, уходит в **не измерено** с названной
  причиной, а не в ноль (инв. #17).
* Обход упёрся в потолок узлов ⇒ строка читателя помечается усечённой и в
  знаменатель находки не идёт: «не досмотрели» не имеет права читаться как
  «не нашли».

Прибор только ЧИТАЕТ: капитал не двигается, живой трек и ``data/`` не
трогаются, зов идёт против КОПИИ-стенда, ``write=False`` проводится там, где
параметр есть (правилом ``module_driver``, а не своей копией правила).
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
from typing import Dict, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import _list_identity_probe as probe  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.monitoring.call_provenance import describe as provenance_line  # noqa: E402,E501
from spa_core.monitoring.python_reader_clock_doors import (  # noqa: E402
    measurement_due, population,
)
from spa_core.monitoring.run_identity_key_price import build_stands  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed, observed_number  # noqa: E402

SCHEMA = "list_identity_census.v1"
ARTIFACT = "list_identity_census.json"
#: Какой МОДУЛЬ собрал документ. Отвечает не на тот вопрос, что `invoked_by`
#: (кто его позвал), и держать их рядом — единственный способ не спутать:
#: у соседа G33 одно лишь `generated_by` и создало впечатление записанного
#: провенанса там, где записана константа.
PRODUCER = "spa_core/monitoring/list_identity_census.py"

#: Такт переписи. Зов каждого читателя стоит секунды, всё население — минуты;
#: ответ на вопрос «как устроены списки» меняется со скоростью кода, а не дня,
#: поэтому такт недельный и срок решает ФАЙЛ (тот же приём, что у соседа G33).
MEASUREMENT_TACT_DAYS = 7

#: Потолок времени на зов всего населения. Превышен ⇒ НЕ ИЗМЕРЕНО с причиной.
PROBE_TIMEOUT_S = 1800

#: Исходы, у которых вопрос заказа ОСМЫСЛЕН: элементы — словари, а значит могли
#: бы назвать себя полем. Список скаляров сюда не входит: он не назван полем не
#: оттого, что списку имён недостаёт имени.
_DICT_OUTCOMES = ("unnamed_candidate_outside", "unnamed_no_candidate")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def run_probe(names: Sequence[str], stand: Path, tree_root: Path,
              moment: dt.datetime) -> Tuple[Optional[dict], str]:
    """Один зов населения — отдельным процессом.

    Отдельный процесс здесь не ради пина часов (его нет вовсе), а ради импорта:
    перепись втягивает под сотню читателей, и побочные эффекты их импорта не
    имеют права оседать в процессе, который потом пишет артефакт.
    """
    with tempfile.TemporaryDirectory(prefix="spa_g34_") as tmp:
        mods = Path(tmp) / "modules.json"
        out = Path(tmp) / "answer.json"
        mods.write_text(json.dumps(list(names)), encoding="utf-8")
        env = dict(os.environ)
        env[probe.STAND_ENV] = str(stand)
        env[probe.CLOCK_ENV] = moment.isoformat()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(tree_root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.monitoring._list_identity_probe",
                 str(mods), str(out)],
                cwd=str(tree_root), env=env, capture_output=True,
                timeout=PROBE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return None, f"зов населения не уложился в {PROBE_TIMEOUT_S} с"
        if proc.returncode != 0 or not out.exists():
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
            return None, f"зонд вышел кодом {proc.returncode}: {tail}"
        try:
            return json.loads(out.read_text(encoding="utf-8")), ""
        except (OSError, ValueError) as exc:
            return None, f"ответ зонда не прочитан: {type(exc).__name__}"


#: Имена, которых у публичной поверхности этого модуля быть НЕ ДОЛЖНО.
#: Прибор отвечает на вопрос «сколько имён берёт каждая пара порогов», а не
#: «годно ли имя»: порог не назначен ни один, и выбрать его вправе только
#: решение. Состав пина — тот же приём, что у соседа (ADR-539): правило
#: «гейта нет» проверяется СОСТАВОМ имён модуля, иначе гейт однажды появится
#: тихой правкой, а прозаическая оговорка в докстринге останется.
_NO_GATE_NAMES = ("apply_threshold", "chosen_pair", "reject_field", "is_fit",
                  "admit_field", "unfit_for_identity", "threshold_gate")


def _ranked_by_population(freq: Dict[str, int],
                          strength: Dict[str, int]) -> List[Tuple[str, int]]:
    """Порядок по НАСЕЛЕНИЮ имени — вторая половина пары, не замена первой.

    Заказ G91 п. 2 начинается словами «население имени — РЯДОМ с длиной, а не
    вместо неё», и это не стилистика. Печать уже несла обе половины
    (``имя×N (макс. длина L)``), но УКОРОЧЕНИЕ перечня в отчёте офиса резало
    хвост по ОДНОЙ оси — по длине. Замер 02.10 на живом артефакте: при
    ``max_fields=8`` восьмёрка по длине кончается на ``journal_pp`` (длина 9,
    ×1), а ``forward_date`` — самое населённое имя переписи (×11) и один из двух
    примеров, которыми заказ и обосновал пару, — в отчёт офиса не попадает
    ВОВСЕ. Голова по населению печатается рядом ровно поэтому; складывать две
    головы в один порядок нельзя — взвешенный балл был бы тем самым «на глаз».
    """
    def _key(item: Tuple[str, int]):
        field, pop = item
        length = observed_number(strength, field)
        # Длина НЕ ИЗМЕРЕНА ⇒ имя уходит в хвост своей группы по населению, и
        # ОТДЕЛЬНОГО члена-флага для этого здесь НЕ НУЖНО — в отличие от
        # порядка по длине (`_rank`), где длина есть ПЕРВЫЙ ключ и флаг
        # обязателен. Разница измерена мутацией (цикл #753): флаг в этом ключе
        # оказался мутационно-эквивалентным, то есть не менял ни одного
        # порядка, — а член без наблюдаемого следствия есть украшение, и держать
        # его «для симметрии» значило бы оставить в наборе утверждение, которое
        # никакой контроль не в силах опровергнуть.
        return (-pop, -length if length is not None else 0, field)

    return sorted(freq.items(), key=_key)


def threshold_grid(freq: Dict[str, int], strength: Dict[str, int]) -> dict:
    """Сетка порогов по ПАРЕ чисел: сколько имён берёт каждая пара и КАКИЕ.

    Заказ G91 п. 2 дословно: «порог по ПАРЕ чисел не назначать на глаз —
    сначала замерить, сколько имён каждая пара порогов берёт и что среди
    взятых». Отсюда три свойства замера, и каждое держит заказ, а не вкус:

    * **Оси — НАБЛЮДЁННЫЕ значения**, а не круглые числа и не равномерный шаг.
      Выбрать шаг сетки на глаз значит выбрать на глаз и порог, только спрятав
      выбор в оформление. Наблюдённые значения дают ровно те пары, между
      которыми вообще есть разница: между 8 и 9 она есть, между 12 и 13 — нет.
    * **У имени в ячейке ТРИ исхода, и третий назван** (инв. #17). Длина у
      имени может быть не измерена; тогда исход решает другая ось либо не
      решает никто, и в «не взято» такое имя НЕ складывается.
    * **Два прочтения пары, и они не суммируются.** ``both`` — имя обязано
      пройти обе оси, ``either`` — достаточно одной. Разделение не косметика:
      заказ привёл два имени, у каждого из которых одна ось сильна, а другая
      нища, и конъюнкция с дизъюнкцией судят их ПРОТИВОПОЛОЖНО. Одно число на
      две разные ставки было бы ответом, не относящимся ни к одной.

    Вердикт правила (``rule_verdict``) ВЫЧИСЛЯЕТСЯ из замера, а не объявляется
    строкой: он держится на двух наблюдаемых условиях (ниже), и если население
    однажды их не предъявит, вердикт сменится САМ — отказ пересматривается
    решением, а не ветшает молча.

    Гейта здесь нет ни одного: прибор печатает цену каждой пары, выбор пары —
    предмет ADR. Правило «гейта нет» пинится составом публичных имён модуля
    (``_NO_GATE_NAMES``), а не обещанием в этом абзаце.
    """
    names = sorted(freq)
    if not names:
        return {"status": "UNMEASURED",
                "reason": "кандидатов нет — пару порогов мерить не на чем"}
    # Длина — ЧИСЛО ЭЛЕМЕНТОВ, то есть целое. `observed_number` отдаёт float,
    # и печатать «L≥93.0» значило бы предъявить дробный порог там, где дробных
    # значений не бывает. Нецелое значение при этом НЕ приводится к целому
    # молча: такого в документе быть не может, а если оно появилось — документ
    # не то, чем себя называет, и это третий исход с названной причиной
    # (инв. #17), а не «длина 92».
    length_of: Dict[str, Optional[int]] = {}
    not_integral: List[str] = []
    for name in names:
        raw = observed_number(strength, name)
        if raw is None:
            length_of[name] = None
        elif float(raw).is_integer():
            length_of[name] = int(raw)
        else:
            length_of[name] = None
            not_integral.append(name)
    pops = sorted({int(freq[name]) for name in names})
    lens = sorted({v for v in length_of.values() if v is not None})
    if not lens:
        return {"status": "UNMEASURED",
                "reason": ("ни у одного кандидата длина не измерена — второй "
                           "оси у пары нет, и сетка по одной оси была бы "
                           "ответом на другой вопрос")}

    cells: List[dict] = []
    for n_min in pops:
        for l_min in lens:
            both_taken, both_unmeasured = [], []
            either_taken, either_unmeasured = [], []
            for name in names:
                pop = int(freq[name])
                length = length_of[name]
                # КОНЪЮНКЦИЯ. Ось населения решает первой: не прошла — исход
                # решён и длина не нужна. Прошла, а длина не измерена — исход
                # решала бы ИМЕННО она, значит «не измерено», а не «не взято».
                if pop >= n_min:
                    if length is None:
                        both_unmeasured.append(name)
                    elif length >= l_min:
                        both_taken.append(name)
                # ДИЗЪЮНКЦИЯ. Достаточно одной оси, поэтому неизмеренная длина
                # мешает только тогда, когда население УЖЕ не прошло.
                if pop >= n_min or (length is not None and length >= l_min):
                    either_taken.append(name)
                elif length is None:
                    either_unmeasured.append(name)
            cells.append({
                "n_min": n_min, "l_min": l_min,
                "both": {"taken": len(both_taken), "names": both_taken,
                         "length_unmeasured": len(both_unmeasured)},
                "either": {"taken": len(either_taken), "names": either_taken,
                           "length_unmeasured": len(either_unmeasured)},
            })

    # ЧЕМПИОНЫ осей — множества, а не по одному имени: ничья на оси длины
    # наблюдена (два имени при 93), и взять из неё одно «первое» значило бы
    # скрыть ровно то совпадение, вокруг которого крутится вердикт.
    top_pop = max(int(freq[name]) for name in names)
    top_len = max(lens)
    champions = {
        "by_population": {
            "value": top_pop,
            "names": sorted(n for n in names if int(freq[n]) == top_pop)},
        "by_max_length": {
            "value": top_len,
            "names": sorted(n for n in names if length_of[n] == top_len)},
    }
    all_champions = set(champions["by_population"]["names"]) | set(
        champions["by_max_length"]["names"])
    # Ячейки, где конъюнкция берёт ОБОИХ чемпионов. Если такие есть только при
    # поле на полу своей оси — порог по этой оси не делает работы вовсе.
    champion_cells = [c for c in cells
                      if all_champions <= set(c["both"]["names"])]
    population_axis_idle = bool(champion_cells) and all(
        c["n_min"] == pops[0] for c in champion_cells)
    length_axis_idle = bool(champion_cells) and all(
        c["l_min"] == lens[0] for c in champion_cells)

    # СЛЕПОЕ ПЯТНО пары. Имена с ОДИНАКОВОЙ координатой ``(население, длина)``
    # неразличимы любым порогом по этим двум числам — это свойство пары, а не
    # наблюдение дня, и именно оно решает вердикт.
    coords: Dict[Tuple[int, int], List[str]] = {}
    for name in names:
        length = length_of[name]
        if length is None:
            continue
        coords.setdefault((int(freq[name]), int(length)), []).append(name)
    collisions = [{"population": pop, "max_length": length,
                   "names": sorted(group)}
                  for (pop, length), group in sorted(coords.items())
                  if len(group) > 1]
    blind_names = sorted(n for c in collisions for n in c["names"])
    coordinate_unmeasured = sorted(n for n in names if length_of[n] is None)

    reasons: List[str] = []
    if blind_names:
        reasons.append(
            f"у {len(blind_names)} имён координата ПОВТОРЯЕТСЯ "
            f"({len(collisions)} класс(ов) совпадения): порог по этой паре "
            f"чисел не различает их ни при каком значении")
    if population_axis_idle:
        reasons.append(
            f"оба чемпиона осей конъюнкция берёт только при n_min={pops[0]}, "
            f"то есть на полу оси населения — порог по населению не делает "
            f"работы вовсе")
    if length_axis_idle:
        reasons.append(
            f"оба чемпиона осей конъюнкция берёт только при l_min={lens[0]} — "
            f"порог по длине не делает работы вовсе")
    if not champion_cells:
        reasons.append("ни одна пара не берёт оба чемпиона осей сразу")
    return {
        "status": "MEASURED",
        "axes": {"population": pops, "max_length": lens},
        "axes_source": ("наблюдённые значения населения переписи — шаг сетки на "
                        "глаз не выбран ни по одной оси"),
        "readings": ["both", "either"],
        "pairs": len(cells),
        "cells": cells,
        "champions": champions,
        "champion_cells": [{"n_min": c["n_min"], "l_min": c["l_min"]}
                           for c in champion_cells],
        "population_axis_idle": population_axis_idle,
        "length_axis_idle": length_axis_idle,
        "collisions": collisions,
        "blind_names": blind_names,
        "coordinate_unmeasured": coordinate_unmeasured,
        "coordinate_not_integral": sorted(not_integral),
        "rule_verdict": "REFUSED" if reasons else "NOT_REFUTED",
        "rule_verdict_reasons": reasons,
        "what_it_does_not_prove": [
            "ни один порог НЕ назначен и ни один гейт не заведён — прибор "
            "называет цену каждой пары, выбор пары есть решение",
            "«не опровергнуто» (NOT_REFUTED) не значит «правило годно»: это "
            "лишь отсутствие двух названных улик на СЕГОДНЯШНЕМ населении",
            "обе оси — наблюдения одного ответа читателей, а не обещание "
            "писателя: население и длина меняются со скоростью кода",
        ],
    }


def distinct_taken_sets(grid: dict, reading: str = "both") -> List[dict]:
    """Различные наборы взятых имён — и СИЛЬНЕЙШАЯ пара, дающая каждый.

    Пар в сетке десятки, а различных ОТВЕТОВ у них единицы: печатать все пары
    значило бы утопить ответ заказа («что среди взятых») в таблице. Выбор
    представителя не на глаз: среди пар с одинаковым набором берётся
    сильнейшая — наибольшая по ``(n_min, l_min)``, то есть та, которая этот
    набор удерживает при самых строгих порогах.
    """
    cells = (grid or {}).get("cells")
    if not cells:
        return []
    best: Dict[Tuple[str, ...], dict] = {}
    for cell in cells:
        side = cell.get(reading) or {}
        key = tuple(side.get("names") or ())
        prev = best.get(key)
        here = (int(cell["n_min"]), int(cell["l_min"]))
        if prev is None or here > (int(prev["n_min"]), int(prev["l_min"])):
            best[key] = {"n_min": cell["n_min"], "l_min": cell["l_min"],
                         "taken": side.get("taken"), "names": list(key),
                         "length_unmeasured": side.get("length_unmeasured")}
    return sorted(best.values(), key=lambda row: (-int(row["taken"] or 0),
                                                 row["n_min"], row["l_min"]))


def tally(rows: Dict[str, dict]) -> dict:
    """Свод по СПИСКАМ, а не по читателям: предмет заказа — список.

    Знаменатель находки назван явно и он УЖЕ полного населения: из него
    вычтены синглтоны (годность в них тривиальна) и списки не-словарей (полем
    себя не называют по построению). Складывать их в один знаменатель значило
    бы развести находку водой.
    """
    outcomes: Dict[str, int] = {}
    candidate_fields: Dict[str, int] = {}
    strength: Dict[str, int] = {}
    named_fields: Dict[str, int] = {}
    singletons = 0
    truncated_readers: List[str] = []
    finding_rows: List[dict] = []
    total_lists = 0
    readers_measured = 0
    unmeasured: Dict[str, int] = {}

    for module, row in sorted(rows.items()):
        cause = row.get("cause")
        if cause:
            unmeasured[str(cause)] = unmeasured.get(str(cause), 0) + 1
            continue
        readers_measured += 1
        if row.get("truncated"):
            truncated_readers.append(module)
        for item in (row.get("lists") or []):
            total_lists += 1
            outcome = str(item.get("outcome"))
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if int(item.get("n") or 0) == 1:
                singletons += 1
            if outcome == "named":
                named_fields[str(item.get("field"))] = (
                    named_fields.get(str(item.get("field")), 0) + 1)
            if outcome == "unnamed_candidate_outside" and int(item.get("n") or 0) > 1:
                for field in (item.get("candidates") or []):
                    candidate_fields[str(field)] = candidate_fields.get(str(field), 0) + 1
                    # Сила свидетельства — ДЛИНА списка, на котором поле
                    # оказалось уникальным. На двух элементах уникальность
                    # почти неизбежна и потому мало что говорит; на сорока
                    # трёх — говорит много. Хранится максимум: он и есть
                    # лучшее наблюдение в пользу поля.
                    prev = strength.get(str(field), 0)
                    strength[str(field)] = max(prev, int(item.get("n") or 0))
                finding_rows.append({"module": module,
                                     "coord": item.get("coord"),
                                     "n": item.get("n"),
                                     "candidates": item.get("candidates")})

    # Знаменатель считается ТОЛЬКО по читателям, чей обход дошёл до конца.
    # Усечённый обход даёт находки (они наблюдены), но не даёт знаменателя:
    # доля, посчитанная от недосмотренного населения, есть «не измерено»,
    # выданное за ответ.
    #
    # И только по СЛОВАРЯМ длиннее одного. Первая редакция брала сюда всякий
    # исход, начинающийся на `unnamed_`, — то есть и списки СКАЛЯРОВ, которых
    # в населении большинство. Знаменатель раздувался вчетверо, а подпись под
    # ним говорила «словари»: ровно то расхождение имени с населением, ради
    # которого весь этот прибор и написан.
    unnamed_dicts_multi = sum(
        1 for row in rows.values()
        if not row.get("cause") and not row.get("truncated")
        for item in (row.get("lists") or [])
        if int(item.get("n") or 0) > 1
        and str(item.get("outcome")) in _DICT_OUTCOMES)
    # Списки СКАЛЯРОВ длиннее одного. Заказ G35 п. 3 (он же G37 п. 4) исполнен:
    # элемент в них называет себя СВОИМ ЗНАЧЕНИЕМ, и правило это теперь не в
    # тексте комментария, а в `element_identity`. Поэтому число разложено на три,
    # а не оставлено одним: слитое `scalar_lists_multi` после правила означало бы
    # уже не то, что означало до неё, и упало бы с 640 до остатка МОЛЧА.
    #
    # И заодно исправлен знаменатель: прежняя редакция считала здесь ВСЁ
    # `unnamed_not_dicts` (>1), то есть вместе со списками списков и смешанными —
    # под подписью «списки скаляров». Теперь состав спрашивается у причины отказа.
    def _count(pred) -> int:
        return sum(
            1 for row in rows.values()
            if not row.get("cause") and not row.get("truncated")
            for item in (row.get("lists") or [])
            if int(item.get("n") or 0) > 1 and pred(item))

    named_by_value = _count(
        lambda item: str(item.get("outcome")) == "named_by_value")
    scalar_not_unique = _count(
        lambda item: str(item.get("outcome")) == "unnamed_not_dicts"
        and str(item.get("scalar_refused")) == "not_unique")
    not_scalar_at_all = _count(
        lambda item: str(item.get("outcome")) == "unnamed_not_dicts"
        and str(item.get("scalar_refused")) == "not_scalar")
    # Строка без названной причины. Живой зонд её не производит (`classify_list`
    # ставит причину всегда), но сложить такую строку «никуда» значило бы дать ей
    # исчезнуть из ВСЕХ трёх чисел молча — а именно так выглядит расхождение
    # зонда со сводом, если оно однажды случится. Третий исход назван (инв. #17).
    cause_unmeasured = _count(
        lambda item: str(item.get("outcome")) == "unnamed_not_dicts"
        and str(item.get("scalar_refused")) not in ("not_unique", "not_scalar"))
    return {
        # Списки ОДНИХ скаляров: получившие личность плюс отказанные за
        # повтор значений. Смешанные и вложенные сюда не входят — они не
        # списки скаляров, и считать их здесь значило бы разводить число водой.
        "scalar_lists_multi": named_by_value + scalar_not_unique,
        "scalar_named_by_value": named_by_value,
        "scalar_not_unique": scalar_not_unique,
        "not_scalar_lists_multi": not_scalar_at_all,
        "scalar_cause_unmeasured": cause_unmeasured,
        "lists_total": total_lists,
        "outcomes": outcomes,
        "singletons": singletons,
        "readers_measured": readers_measured,
        "unmeasured_causes": unmeasured,
        "truncated_readers": sorted(truncated_readers),
        "named_fields": named_fields,
        "candidate_fields_outside": candidate_fields,
        "candidate_field_strength": strength,
        # Заказ G91 п. 2: ПАРА чисел («население × длина»), замеренная сеткой
        # наблюдённых значений. Складывать её в одно число с полями выше
        # нельзя — это ответ на другой вопрос: не «какие поля годны», а «что
        # взяла бы каждая пара порогов, если бы её назначили».
        "threshold_grid": threshold_grid(candidate_fields, strength),
        "denominator_of_finding": unnamed_dicts_multi,
        "finding_rows": finding_rows,
    }


def measure(data_dir: Path, tree_root: Path, *,
            now: Optional[dt.datetime] = None) -> dict:
    """Перепись целиком. Любое незакрытое звено ⇒ ``UNMEASURED`` с причиной."""
    moment = now if now is not None else _utcnow()
    doc: dict = {
        "schema": SCHEMA,
        "generated_at": moment.isoformat(),
        # Заказ G36 п. 1. `generated_at` — часы, а не звавший: отметка сменится
        # одинаково, позвала ли перепись ступень моста или рука цикла, набравшая
        # `python3 -m`. Без этого поля наблюдение 25.09 односторонне — оно может
        # ОПРОВЕРГНУТЬ проводку ступени и не может её подтвердить.
        "invoked_by": call_provenance(tree_root=Path(tree_root)),
        "generated_by": PRODUCER,
        "question": ("сколько списков в ответах питоньих читателей не называют "
                     "себя полем (третий исход element_identity) и у скольких "
                     "есть годное поле-кандидат вне _IDENTITY_FIELDS"),
        "what_it_does_not_prove": [
            "годность поля наблюдена на ОДНОМ ответе — это не обещание писателя",
            "синглтон годен тривиально: уникальность в списке из одного элемента "
            "есть совпадение, а не свойство — синглтоны вынесены из знаменателя",
            "усечённый обход в знаменатель находки не идёт: «не досмотрели» не "
            "есть «не нашли»",
            "перепись НЕ дописывает имена в _IDENTITY_FIELDS и не меняет ни одной "
            "координаты — она только называет цену нынешнего списка",
        ],
        "advisory": ("_IDENTITY_FIELDS, element_identity, координаты соседних "
                     "приборов, пороги RiskPolicy v1.0, стоп-кран и живой трек "
                     "НЕ трогаются — прибор только ЧИТАЕТ"),
        "identity_fields_today": list(probe.IDENTITY_FIELDS),
    }

    names, pop_stats = population(Path(tree_root))
    doc["population"] = pop_stats
    if not names:
        doc["status"] = "UNMEASURED"
        doc["reason"] = "питонья ветвь населения переписи пуста — звать некого"
        return doc

    with tempfile.TemporaryDirectory(prefix="spa_g34_stand_") as tmp:
        stands, why = build_stands(Path(data_dir), Path(tmp))
        if stands is None:
            doc["status"] = "UNMEASURED"
            doc["reason"] = f"стенд не построен: {why}"
            return doc
        doc["stand"] = {"day": stands.get("day"), "donor_day": stands.get("donor_day")}
        answer, why = run_probe(names, Path(stands["s1"]), Path(tree_root), moment)
        if answer is None:
            doc["status"] = "UNMEASURED"
            doc["reason"] = f"население не позвано: {why}"
            return doc

    rows = answer.get("__modules__") or {}
    doc["readers"] = rows
    doc["counts"] = tally(rows)
    if not doc["counts"]["readers_measured"]:
        doc["status"] = "UNMEASURED"
        doc["reason"] = ("ни один читатель не позван — знаменателя нет, и ноль "
                         "находок читался бы как ответ")
        return doc
    finding = len(doc["counts"]["finding_rows"])
    doc["status"] = "FINDING" if finding else "CLEAN"
    doc["reason"] = (
        f"списков без личности с годным полем ВНЕ списка имён: {finding}"
        if finding else
        "ни один список без личности не имеет годного поля вне _IDENTITY_FIELDS")
    return doc


def grid_report(grid: dict, *, max_cells: int = 12) -> List[str]:
    """Строки сетки порогов. Знаменатель пары — рядом с числителем, как везде."""
    axes = grid.get("axes") or {}
    pops = axes.get("population") or []
    lens = axes.get("max_length") or []
    out = [f"[ПАРА ЧИСЕЛ · ОСИ] население: {', '.join(str(x) for x in pops)} · "
           f"макс. длина: {', '.join(str(x) for x in lens)} ⇒ пар "
           f"{grid.get('pairs')}. {grid.get('axes_source')}"]
    champ = grid.get("champions") or {}
    by_pop = champ.get("by_population") or {}
    by_len = champ.get("by_max_length") or {}
    out.append(f"[ПАРА ЧИСЕЛ · ЧЕМПИОНЫ] по населению ×{by_pop.get('value')}: "
               f"{', '.join(by_pop.get('names') or [])} · по длине "
               f"{by_len.get('value')}: {', '.join(by_len.get('names') or [])}")
    for reading, title in (("both", "КОНЪЮНКЦИЯ (обе оси)"),
                           ("either", "ДИЗЪЮНКЦИЯ (любая ось)")):
        rows = distinct_taken_sets(grid, reading=reading)
        out.append(f"[ПАРА ЧИСЕЛ · {title}] различных ответов у "
                   f"{grid.get('pairs')} пар: {len(rows)} — ниже сильнейшая "
                   f"пара каждого ответа")
        for row in rows[:max_cells]:
            names = ", ".join(row.get("names") or []) or "— ничего"
            # `or 0` здесь был бы ровно инв. #17 наизнанку: ячейка, у которой
            # счётчика неизмеренных НЕТ, напечаталась бы как «неизмеренных
            # ноль». Поймано храповиком класса на этой самой строке.
            unmeasured = observed_number(row, "length_unmeasured")
            if unmeasured is None:
                tail = ("; скольким именам длина не измерена — НЕ СКАЗАНО, и "
                        "это не ноль")
            elif unmeasured:
                tail = f"; длина не измерена у {int(unmeasured)}"
            else:
                tail = ""
            out.append(f"   n≥{row.get('n_min')} и L≥{row.get('l_min')}: "
                       f"взято {row.get('taken')} — {names}{tail}")
        if len(rows) > max_cells:
            out.append(f"   … ещё {len(rows) - max_cells} ответ(ов) — полный "
                       f"перечень в {ARTIFACT}")
    # Перечень классов совпадения НЕСЁТ вердикт, поэтому его отсутствие — не
    # «пятна нет», а отсутствие замера: пустой список и отсутствующий ключ
    # отвечают на разные вопросы (инв. #17).
    collisions = observed(grid, "collisions", kind=list)
    if collisions is None:
        out.append("[ПАРА ЧИСЕЛ · НЕ ИЗМЕРЕНО] перечня классов совпадения в "
                   "сетке нет вовсе — это не «совпадающих координат нет»")
        collisions = []
    elif collisions:
        shown = "; ".join(
            f"({c.get('population')}, {c.get('max_length')}): "
            f"{', '.join(c.get('names') or [])}" for c in collisions[:max_cells])
        out.append(f"[ПАРА ЧИСЕЛ · СЛЕПОЕ ПЯТНО] координата повторяется у "
                   f"{len(grid.get('blind_names') or [])} имён в "
                   f"{len(collisions)} класс(ах): {shown} — внутри класса пара "
                   f"порогов не различает имена НИ ПРИ КАКОМ значении")
    else:
        out.append("[ПАРА ЧИСЕЛ · СЛЕПОЕ ПЯТНО] совпадающих координат нет — "
                   "пара различает все имена населения")
    if grid.get("coordinate_not_integral"):
        out.append(f"[ПАРА ЧИСЕЛ · НЕ ИЗМЕРЕНО] длина НЕ ЦЕЛАЯ у "
                   f"{len(grid['coordinate_not_integral'])} имён: "
                   f"{', '.join(grid['coordinate_not_integral'])} — число "
                   f"элементов дробным не бывает, и округлять его значило бы "
                   f"выдать поправку за наблюдение")
    if grid.get("coordinate_unmeasured"):
        out.append(f"[ПАРА ЧИСЕЛ · НЕ ИЗМЕРЕНО] длины нет у "
                   f"{len(grid['coordinate_unmeasured'])} имён: "
                   f"{', '.join(grid['coordinate_unmeasured'])} — они не "
                   f"сложены в «не взято» ни в одной ячейке")
    verdict = grid.get("rule_verdict")
    reasons = grid.get("rule_verdict_reasons") or []
    out.append(f"[ПАРА ЧИСЕЛ · ВЕРДИКТ ПРАВИЛА] {verdict}"
               + (": " + " · ".join(reasons) if reasons else
                  " — названных улик против пары на СЕГОДНЯШНЕМ населении нет; "
                  "это не «правило годно»"))
    out.append("[ПАРА ЧИСЕЛ · ГЕЙТА НЕТ] ни один порог не назначен и ни одно "
               "имя не дописано в _IDENTITY_FIELDS: выбор пары — предмет ADR, "
               "а не прибора")
    return out


def report(doc: dict, *, max_rows: int = 20,
           max_fields: Optional[int] = None,
           max_cells: int = 12) -> List[str]:
    """Отчёт. Знаменатель печатается рядом с числителем — всегда."""
    out = [f"Перепись личности списков (G34 п. 1) — {doc.get('status')}"]
    # Звавший печатается ДО раннего возврата намеренно: на документе UNMEASURED
    # вопрос «кто это позвал» не менее интересен, чем на измеренном, — именно
    # так выглядел бы прогон, который ступень моста завела, а стенд не построила.
    # Запись, которую никто не читает, — это ADR-259, и заводить её второй раз,
    # зная о классе, значило бы его воспроизвести.
    out.append(f"[ЗВАВШИЙ] {provenance_line(observed(doc, 'invoked_by', kind=dict))}")
    if doc.get("status") == "UNMEASURED":
        out.append(f"[НЕ ИЗМЕРЕНО] {doc.get('reason')}")
        return out
    # Счётчиков нет ВООБЩЕ — документ не является замером, и подставлять
    # пустой словарь значит печатать нули там, где не мерили (инв. #17).
    # Найдено храповиком `test_absent_observation_ratchet` на этом самом файле:
    # он приехал на origin вчера (#626) уже красным — база класса этих двух мест
    # не знает. Погашено ЧИНКОЙ чтения, а не дописью в базу (база только
    # уменьшается, `.claude/rules/deployment.md`).
    c = observed(doc, "counts", kind=dict)
    if c is None:
        out.append("[НЕ ИЗМЕРЕНО] у документа нет счётчиков вовсе — это не "
                   "«ноль находок», а отсутствие замера")
        return out
    named = int((c.get("outcomes") or {}).get("named") or 0)
    out.append(f"[ОТВЕТ] списков в ответах: {c.get('lists_total')} · "
               f"называют себя полем: {named} · "
               f"третий исход (личности нет): {c.get('lists_total', 0) - named}")
    out.append(f"[ЗНАМЕНАТЕЛЬ] списков без личности, где вопрос ОСМЫСЛЕН "
               f"(словари, длина > 1): {c.get('denominator_of_finding')}; "
               f"синглтонов всего {c.get('singletons')} — их годность тривиальна "
               f"и в знаменатель не входит")
    out.append(f"[РЯДОМ, НЕ В ЗНАМЕНАТЕЛЕ] списков СКАЛЯРОВ длиннее одного: "
               f"{c.get('scalar_lists_multi')} — полем себя не называют по "
               f"построению, но обходятся позиционно, а элемент в них назван "
               f"своим значением; это соседний вопрос, не этот")
    called = c.get("readers_measured")
    out.append(f"[ПОЗВАНО] читателей ответило: "
               f"{called if called is not None else 'НЕ ИЗМЕРЕНО'} — "
               f"неотвечавшие названы ниже ПРИЧИНОЙ, а не нулём (инв. #17)")
    for key in sorted(c.get("outcomes") or {}):
        out.append(f"[ПО ИСХОДАМ] {key}: {(c.get('outcomes') or {})[key]}")
    fields = c.get("candidate_fields_outside") or {}
    if fields:
        strength = c.get("candidate_field_strength") or {}
        # Порядок — по ДЛИНЕ, а не по частоте (ADR-410): уникальность на двух
        # элементах почти неизбежна, поэтому частотный чемпион в укороченном
        # перечне возглавил бы список, свидетельствуя слабее любого из
        # отброшенных. Пока перечень печатался ЦЕЛИКОМ, порядок был косметикой;
        # как только у него появился читатель с укорочением (`max_fields`,
        # заказ G35 п. 5), порядок стал утверждением — и он обязан совпадать с
        # тем, что сам же прибор говорит про силу свидетельства.
        def _rank(item):
            field, freq = item
            length = observed_number(strength, field)
            # НЕИЗМЕРЕННАЯ длина — не нулевая (инв. #17): такое поле уходит в
            # хвост ОТДЕЛЬНОЙ группой, а не притворяется слабейшим из
            # измеренных, иначе «силы нет» и «сила мала» слились бы в одно.
            return (0 if length is not None else 1,
                    -length if length is not None else 0, -freq, field)

        ranked = sorted(fields.items(), key=_rank)
        shown = ranked if max_fields is None else ranked[:max_fields]
        named_fields = ", ".join(
            f"{k}×{v} (макс. длина {strength.get(k, '?')})" for k, v in shown)
        tail = ("" if len(shown) == len(ranked) else
                f"; … ещё {len(ranked) - len(shown)} пол(я) — полный перечень "
                f"в {ARTIFACT}")
        out.append(f"[НАХОДКА] годные поля ВНЕ _IDENTITY_FIELDS "
                   f"(по убыванию ДЛИНЫ подпирающего списка): "
                   f"{named_fields}{tail}")
        out.append("[СИЛА СВИДЕТЕЛЬСТВА] «макс. длина» — длиннейший список, на "
                   "котором поле оказалось уникальным. На двух элементах "
                   "уникальность почти неизбежна и свидетельствует слабо; "
                   "дописывать имя в список по строке с длиной 2 значило бы "
                   "вернуть ту самую догадку")
        # Вторая голова — по НАСЕЛЕНИЮ (заказ G91 п. 2). Печатается РЯДОМ и
        # всегда, а не вместо и не «когда перечень укорочен»: порядок по одной
        # оси при укорочении хвоста выбрасывает чемпиона другой оси, и замер
        # 02.10 это предъявил на живом артефакте (`forward_date` ×11 — за
        # восьмёркой по длине). Два порядка НЕ складываются в один балл:
        # взвесить оси значило бы назначить порог на глаз, что заказ запрещает.
        by_pop = _ranked_by_population(fields, strength)
        pop_shown = by_pop if max_fields is None else by_pop[:max_fields]
        hidden = [k for k, _ in pop_shown if k not in {k2 for k2, _ in shown}]
        pop_line = ", ".join(
            f"{k}×{v} (макс. длина {strength.get(k, '?')})" for k, v in pop_shown)
        out.append(f"[РЯДОМ, ПО НАСЕЛЕНИЮ] те же поля в порядке населения: "
                   f"{pop_line}"
                   + (f"; порядком по длине скрыто: {', '.join(hidden)}"
                      if hidden else "; голова та же, что по длине"))

        rows = observed(c, "finding_rows", kind=list)
        if rows is None:
            out.append("[НЕ ИЗМЕРЕНО] перечня строк-находок у документа нет "
                       "вовсе, а поля-кандидаты есть — документ неполон, и "
                       "пустой перечень тут читался бы как «находок нет»")
            rows = []
        for row in rows[:max_rows]:
            out.append(f"   {row.get('module')} {row.get('coord')} "
                       f"(элементов {row.get('n')}): {', '.join(row.get('candidates') or [])}")
        if len(rows) > max_rows:
            out.append(f"   … ещё {len(rows) - max_rows} строк(и) — полный "
                       f"перечень в {ARTIFACT}")
        # Сетка порогов печатается ПОСЛЕ строк-находок намеренно: она отвечает
        # не на «какие поля годны», а на «что взяла бы пара порогов, если её
        # назначить», и вклинивать её между полями и их строками значило бы
        # разорвать один ответ надвое.
        grid = observed(c, "threshold_grid", kind=dict)
        if grid is None:
            out.append("[НЕ ИЗМЕРЕНО] сетки порогов по паре чисел в документе "
                       "нет вовсе — это не «пара ничего не берёт»")
        elif str(grid.get("status")) != "MEASURED":
            out.append(f"[НЕ ИЗМЕРЕНО] пара порогов: {grid.get('reason')}")
        else:
            out.extend(grid_report(grid, max_cells=max_cells))
    else:
        out.append("[ОПОРА] годных полей вне списка имён не нашлось — нынешний "
                   "список имён не занижает личность ни у одного списка населения")
    if c.get("truncated_readers"):
        out.append(f"[НЕ ДОСМОТРЕНО] обход упёрся в потолок у читателей: "
                   f"{', '.join(c['truncated_readers'])} — их списки в знаменатель "
                   f"находки не включены")
    causes = observed(c, "unmeasured_causes", kind=dict)
    if causes is None:
        out.append("[НЕ ИЗМЕРЕНО] перечня причин у непозванных читателей в "
                   "документе нет — их отсутствие не есть «позваны все»")
    else:
        for cause, num in sorted(causes.items()):
            out.append(f"[НЕ ИЗМЕРЕНО] {cause}: {num} читател(ей)")
    out.append(f"ADVISORY: {doc.get('advisory')}")
    return out


def format_report(doc: dict, *, max_rows: int = 5,
                  max_fields: int = 8, max_cells: int = 6) -> List[str]:
    """Строки для ЧИТАТЕЛЯ переписи — обязательного шага 0-офис (заказ G35 п. 5).

    Второй копии правила отрисовки здесь НЕТ намеренно: ветка шага 0-офис
    делегирует сюда, а эта функция — в ``report``, поэтому расхождение «в
    консоли одно, в отчёте другое» невозможно по построению. Отличий ровно два,
    и оба — про читателя, а не про предмет: находка помечается знаком, на
    который у офиса заведено правило «красные строки = действовать», и перечни
    укорачиваются (строк-находок и полей-кандидатов; полный перечень лежит в
    артефакте, и строка об укорочении это говорит). Укорочение — единственная
    причина, по которой ПОРЯДОК полей стал утверждением, а не косметикой:
    режется хвост, значит голова обязана быть сильнейшим свидетельством, то
    есть самым ДЛИННЫМ списком, а не самым частым именем.
    """
    lines = report(doc, max_rows=max_rows, max_fields=max_fields,
                   max_cells=max_cells)
    if str(doc.get("status")) == "FINDING":
        lines[0] = f"⚠️ {lines[0]}"
    return lines


def run(root: str | Path = _ROOT, *, data_dir: Optional[Path] = None,
        dest: Optional[Path] = None, write: bool = True, if_due: bool = True,
        now: Optional[dt.datetime] = None,
        tact_days: int = MEASUREMENT_TACT_DAYS) -> dict:
    """Один ТАКТ переписи для ступени моста: мерить, только если срок пришёл.

    Зачем эта обёртка, если есть ``measure``. У ступени переписей
    (``findings_bridge.CENSUS_STAGE``) объявленная форма вызова — ``<модуль>.run(
    root=args.root)``, и она не прихоть: ровно по этой форме сторожа
    (`test_cio_acceptance_guards_are_wired`, `_orphan_producer`) отвечают на
    вопрос «а есть ли на свете вызов, который этот артефакт пишет». Заказ G35
    п. 5 — про то, что у числа не было ни ЧИТАТЕЛЯ, ни автоматического
    производителя: ступень (1ж) соседа живёт СТРОКОЙ В ПРОМПТЕ, а строка не
    есть вызов (замер 18.09: автоматического зова не наблюдалось ни одного).

    **«Не мерили» и «измерено» — РАЗНЫЕ исходы** (инв. #17), поэтому внутри
    такта возвращается ``{"measured": False, "reason": …}`` и НЕ выдумывается
    вердикт переписи: ``CLEAN`` в этой ветке был бы утверждением о населении,
    которого никто не смотрел. Срок решает ФАЙЛ (``measurement_due``), а не
    расписание бегуна: иначе «раз в неделю» держалось бы на том, что никто не
    менял такт агента.
    """
    root = Path(root)
    source = Path(data_dir) if data_dir is not None else root / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    if if_due:
        due, why = measurement_due(target, now=now, tact_days=tact_days)
        if not due:
            return {"measured": False, "reason": why, "artifact": str(target)}
    doc = measure(source, root, now=now)
    if write:
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись списков без личности в ответах питоньих читателей (G34 п. 1)")
    ap.add_argument("--data-dir", default=str(_ROOT / "data"),
                    help="каталог data/, с которого строится стенд (КОПИЯ, не правится)")
    ap.add_argument("--tree-root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--if-due", action="store_true",
                    help=f"мерить, только если со дня прошлого замера прошло "
                         f"{MEASUREMENT_TACT_DAYS} дн")
    args = ap.parse_args(argv)

    dest = Path(args.out) if args.out else Path(args.data_dir) / ARTIFACT
    # Гейт такта живёт в ОДНОМ месте (`run`) — вторая его копия здесь означала
    # бы, что ступень моста и рука владельца судят о сроке по разным правилам.
    outcome = run(Path(args.tree_root), data_dir=Path(args.data_dir), dest=dest,
                  write=not args.no_write, if_due=args.if_due)
    if not outcome["measured"]:
        print(f"замер не назначен: {outcome['reason']}")
        return 0
    doc = outcome["doc"]
    for line in report(doc):
        print(line)
    return {"UNMEASURED": 2, "FINDING": 1}.get(str(doc.get("status")), 0)


if __name__ == "__main__":
    raise SystemExit(main())
