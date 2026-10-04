#!/usr/bin/env python3
"""Шаг стал дороже — от РАБОТЫ или от СРЕДЫ? Замер по паре прогонов.

**Заказ G87 п. 3 — ПЕРЕОТКРЫТ** (хвост [ADR-491](../../docs/decisions/ADR-491-no-regression-criterion-measured-by-outcome.md)).
[ADR-534](../../docs/decisions/ADR-534-where-the-time-of-the-test-step-goes.md) закрыл
его 02.10 и ответил по ОДНОМУ дошедшему прогону: 203,2 мин, «помещается в 240».
Через сутки шаг потолок перешёл. Вывод «помещается» был верен о своём прогоне и неверен
о шаге, и отличить одно от другого одним прогоном НЕВОЗМОЖНО по построению: у одной
точки нет разброса.

**Вопрос, на который отвечает этот модуль, и которого у `step_time_census` нет.**
Тот меряет ОДИН прогон и отвечает «куда ушло время внутри него». Этот сравнивает ДВА и
отвечает на другой вопрос: подорожала РАБОТА или подешевела МАШИНА. Прибор здесь не
второй — он читает census первого и своего разбора записи не имеет ни одного
(`census_from_path` — единственная дверь к записи).

**Как различаются два рода подорожания.** Если работы стало больше, дорожает ЧАСТЬ
файлов, и распределение отношений широкое с центром у единицы. Если медленнее стала
машина, дорожают ВСЕ файлы примерно одинаково, и распределение узкое с центром выше
единицы. Поэтому мера — не среднее, а **медиана отношения и межквартильный размах** по
файлам, у которых число случаев в обоих прогонах ОДИНАКОВО: сравнивать файл, в котором
прибавился тест, значило бы смешать оба рода в одном числе.

**Контроль, без которого вывод был бы догадкой.** Матрица CI гоняет один коммит на
py3.11 и py3.12 — два задания одного прогона, разные раннеры, работа тождественна.
Отношение между ними и есть ИЗМЕРЕННЫЙ масштаб «раннер против раннера» на этом парке.
Сравнивать дневной множитель не с нулём, а с ним.

**Три исхода** (инв. #17). Любая из двух записей не прочитана ⇒ `unmeasured:` с
названной причиной. Сопоставимых файлов меньше `MIN_COMPARABLE_FILES` ⇒
`unmeasured:too_few_comparable_files` — на горстке файлов квартили не смысл, а шум.
Оборванная сессия сравнению НЕ мешает (отношения берутся по файлам, а не по стене),
но её стена остаётся нижней границей, и это печатается.

**Чего прибор НЕ докладывает:** ПОЧЕМУ машина медленнее · тренд (две точки тренда не
дают, ADR-473) · вклад отдельной фикстуры · верность самого потолка.

ADVISORY: только ЧИТАЕТ. Только stdlib (инв. #4).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys

from spa_core.monitoring.step_time_census import READ_OK, by_file, census_from_path

#: Меньше этого числа сопоставимых файлов — квартили считать не на чем.
MIN_COMPARABLE_FILES = 100

#: Файлы дешевле этого в опорном прогоне из отношений исключаются: на десятых долях
#: секунды отношение меряет разрешение часов, а не стоимость.
MIN_BASELINE_S = 1.0


def comparable_files(base, later):
    """Файлы, у которых ЧИСЛО случаев в обоих прогонах одинаково.

    Равенство числа случаев — и есть определение «работа та же». Файл, где тест
    добавили или сняли, из отношений исключается: в нём смешаны оба рода.
    """
    nb, nl = {}, {}
    for case in base.cases:
        nb[case.file] = nb.get(case.file, 0) + 1
    for case in later.cases:
        nl[case.file] = nl.get(case.file, 0) + 1
    return {f for f in nb if f in nl and nb[f] == nl[f]}


def drift(base, later, min_baseline_s=MIN_BASELINE_S):
    """Распределение отношения «позже / раньше» по сопоставимым файлам."""
    if base.read != READ_OK:
        return {"verdict": "unmeasured:baseline_%s" % base.read, "reason": base.reason}
    if later.read != READ_OK:
        return {"verdict": "unmeasured:later_%s" % later.read, "reason": later.reason}

    fb, fl = by_file(base), by_file(later)
    shared = comparable_files(base, later)
    ratios = sorted((fl[f] / fb[f], f) for f in shared if fb[f] >= min_baseline_s)
    if len(ratios) < MIN_COMPARABLE_FILES:
        return {"verdict": "unmeasured:too_few_comparable_files",
                "comparable": len(ratios), "needed": MIN_COMPARABLE_FILES}

    values = [r for r, _ in ratios]
    q1 = values[len(values) // 4]
    q3 = values[3 * len(values) // 4]
    slower = sum(1 for r in values if r > 1.0)
    return {
        "verdict": "measured",
        "comparable_files": len(values),
        "median_ratio": statistics.median(values),
        "q1_ratio": q1,
        "q3_ratio": q3,
        "iqr": q3 - q1,
        "share_slower": slower / len(values),
        "cases_base": len(base.cases),
        "cases_later": len(later.cases),
        "case_growth": (len(later.cases) - len(base.cases)) / len(base.cases),
        "span_base_s": base.span_s,
        "span_later_s": later.span_s,
        "base_ended": base.ended,
        "later_ended": later.ended,
        "fastest": ratios[:3],
        "slowest": ratios[-3:][::-1],
    }


def read_as_work_or_environment(result, control_ratio=None):
    """Назвать род подорожания — и отказаться, когда назвать его нечем.

    `control_ratio` — измеренный масштаб «раннер против раннера» (матрица одного
    коммита). Без него вывод сравнивался бы с нулём, а не с разбросом парка, и
    любое отличие от единицы выглядело бы находкой.
    """
    if result.get("verdict") != "measured":
        return result.get("verdict", "unmeasured:unknown")
    uniform = result["iqr"] < 0.25 and result["share_slower"] > 0.90
    if not uniform:
        return "work_changed"
    if control_ratio is None:
        return "unmeasured:no_same_commit_control"
    if result["median_ratio"] <= control_ratio:
        return "within_runner_spread"
    return "environment_beyond_runner_spread"


def render(result, label_base, label_later, control_ratio=None, control_label=None):
    out = ["— подорожание шага: работа или среда (заказ G87 п. 3, переоткрыт) —",
           "   раньше: %s" % label_base, "   позже : %s" % label_later]
    if result.get("verdict") != "measured":
        out.append("   ❗НЕ ИЗМЕРЕНО: %s%s" % (
            result["verdict"],
            "" if "reason" not in result else " (%s)" % result["reason"]))
        out.append("   ADVISORY: прибор только ЧИТАЕТ (applied=False)")
        return "\n".join(out)

    for tag, key, ended in (("раньше", "span_base_s", "base_ended"),
                            ("позже ", "span_later_s", "later_ended")):
        out.append("   стена %s: %.1f мин%s" % (
            tag, result[key] / 60.0, "" if result[ended] else "  (НИЖНЯЯ ГРАНИЦА — сессия оборвана)"))
    out.append("   случаев %d → %d  (%+.1f %%)" % (
        result["cases_base"], result["cases_later"], 100.0 * result["case_growth"]))
    out.append("   сопоставимых файлов (одинаковое число случаев, > %.0f с): %d"
               % (MIN_BASELINE_S, result["comparable_files"]))
    out.append("   отношение позже/раньше: медиана ×%.3f · Q1 ×%.3f · Q3 ×%.3f · размах %.3f"
               % (result["median_ratio"], result["q1_ratio"], result["q3_ratio"], result["iqr"]))
    out.append("   медленнее стали %.0f %% файлов" % (100.0 * result["share_slower"]))
    verdict = read_as_work_or_environment(result, control_ratio)
    if control_ratio is not None:
        out.append("   контроль «раннер против раннера» (%s): ×%.3f" % (control_label or "матрица одного коммита", control_ratio))
    out.append("   ВЕРДИКТ: %s" % verdict)
    out.append("   самые подорожавшие: " + " · ".join("%s ×%.2f" % (f.split("/")[-1], r) for r, f in result["slowest"]))
    out.append("   НЕ ДОКЛАДЫВАЕТ: почему среда медленнее · тренд (две точки его не дают, ADR-473) · "
               "вклад отдельной фикстуры · верность потолка")
    out.append("   ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Подорожание шага: работа или среда (заказ G87 п. 3).")
    ap.add_argument("base", help="потоковая запись БОЛЕЕ РАННЕГО прогона")
    ap.add_argument("later", help="потоковая запись БОЛЕЕ ПОЗДНЕГО прогона")
    ap.add_argument("--control-a", default=None,
                    help="запись задания А матрицы ОДНОГО коммита (контроль среды)")
    ap.add_argument("--control-b", default=None, help="запись задания Б того же прогона")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    base = census_from_path(pathlib.Path(args.base))
    later = census_from_path(pathlib.Path(args.later))
    result = drift(base, later)

    control = None
    if args.control_a and args.control_b:
        c = drift(census_from_path(pathlib.Path(args.control_a)),
                  census_from_path(pathlib.Path(args.control_b)))
        control = c["median_ratio"] if c.get("verdict") == "measured" else None
        result["control"] = c

    result["kind"] = read_as_work_or_environment(result, control)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    else:
        print(render(result, args.base, args.later, control))

    if result.get("verdict") != "measured":
        return 2
    return 1 if result["kind"] != "within_runner_spread" else 0


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
