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

**Где вызывается (23.10).** `scripts/ci_control.py compare --base-shards … --head-shards …`
передаёт сюда записи шардов обоих контрольных прогонов (`compare_sharded`) и кладёт итог
рядом со своим (`step_time_drift` в `--out-json`, текст — в печать). У шардированной пары
контроля «тот же коммит» нет — каждый шард на своей машине, — поэтому род подорожания там
НЕ ИЗМЕРЕН по построению, а числа распределения печатаются как описание. Код возврата
`compare` прибор не меняет.

ADVISORY: только ЧИТАЕТ. Только stdlib (инв. #4).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
from typing import NamedTuple

from spa_core.monitoring.step_time_census import READ_ABSENT, READ_OK, by_file, census_from_path

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
    # Контроль спрашивается ДО формы, а не только для равномерной формы. Широкий
    # размах без контроля НЕ есть улика «работы»: его даёт и разнородность машин.
    # Замер 23.10 на ci-control (62fe88b48 → 5bc06f5db, 12+12 шардов, у каждого свой
    # раннер): общий размах 0.32 при медиане ×1.00, а медианы ВНУТРИ пар «шард базы →
    # шард головы» (66 пар с ≥ 5 файлами) лежат от ×0.57 до ×1.66 — ширину делают
    # машины, а прежняя ветка назвала бы это «work_changed».
    if control_ratio is None:
        return "unmeasured:no_same_commit_control"
    uniform = result["iqr"] < 0.25 and result["share_slower"] > 0.90
    if not uniform:
        return "work_changed"
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


# ── шардированный прогон (`scripts/ci_control.py compare`) ───────────────────
#
# Контрольный прогон CI режет набор на шарды, и у КАЖДОГО шарда — своя машина
# GitHub. Записи шардов — та же потоковая запись `pytest_stream_record`, поэтому
# каждая читается той же дверью `census_from_path`; здесь они только СКЛАДЫВАЮТСЯ.
# Своего разбора записи тут по-прежнему нет.

#: Пар «шард базы → шард головы» с меньшим числом сопоставимых файлов в выжимке
#: разброса не печатаем: медиана трёх файлов — не медиана.
MIN_PAIR_FILES = 5

#: Почему у шардированной пары нет причинного вывода. Это причина отказа, а не оговорка.
NO_CONTROL_REASON = (
    "нет контроля «тот же коммит на других машинах»: у каждого шарда своя машина GitHub, "
    "и отношение файла смешивает работу с машиной его шарда; контролем был бы второй "
    "прогон ci-control ТОГО ЖЕ SHA, а его не передали")


class ShardedRun(NamedTuple):
    """Союз переписей шардов одного прогона. ``read`` != READ_OK ⇒ числа бессмысленны.

    Не выдаёт себя за ``Census``: тождества учёта у союза нет, стена — САМОГО ДОЛГОГО
    шарда (шарды идут параллельно), а не сумма.
    """

    read: str
    reason: str
    cases: tuple
    span_s: float
    ended: bool
    used: tuple                 # индексы шардов, вошедших в союз
    excluded: tuple             # ((шард, причина), ...) — вошли бы, но не годятся
    shard_of_file: dict


def sharded_run(records):
    """Сложить записи шардов. ``records`` — [(шард, тестов по плану, путь к записи)].

    * плана нет ⇒ ``record_absent`` (сравнивать нечего — и это не ноль);
    * запись шарда отсутствует или не читается ⇒ весь прогон НЕ ИЗМЕРЕН с названным
      шардом: недостающий шард мог нести любые файлы;
    * в записи несколько сессий (шард доигрывался) ⇒ шард ИСКЛЮЧЁН с причиной:
      перепись берёт последнюю сессию, и часть файлов в ней неполна;
    * случаев в записи не столько, сколько тестов в плане шарда ⇒ ИСКЛЮЧЁН: запись
      не от этого отчёта или шард не дошёл.
    """
    records = list(records or [])
    if not records:
        return ShardedRun(READ_ABSENT, "отчёт не объявил ни одного шарда", (), 0.0, False,
                          (), (), {})
    cases, used, excluded, spans, ended, owner = [], [], [], [], True, {}
    for shard, planned, path in records:
        c = census_from_path(pathlib.Path(path) if path is not None else None)
        if c.read != READ_OK:
            return ShardedRun(c.read, "шард %s: %s" % (shard, c.reason), (), 0.0, False,
                              (), (), {})
        if c.sessions_in_record != 1:
            excluded.append((shard, "сессий в записи %d: перепись читает последнюю, файлы "
                                    "ранних сессий неполны" % c.sessions_in_record))
            continue
        if planned is None or len(c.cases) != planned:
            excluded.append((shard, "случаев в записи %d, тестов в плане шарда %s"
                                    % (len(c.cases), planned)))
            continue
        used.append(shard)
        cases.extend(c.cases)
        spans.append(c.span_s)
        ended = ended and c.ended
        for case in c.cases:
            owner[case.file] = shard
    if not used:
        return ShardedRun("no_usable_shards", "ни один шард не годится: %s" % "; ".join(
            "%s — %s" % e for e in excluded), (), 0.0, False, (), tuple(excluded), {})
    return ShardedRun(READ_OK, "", tuple(cases), max(spans), ended, tuple(used),
                      tuple(excluded), owner)


def shard_pair_spread(base, later, min_baseline_s=MIN_BASELINE_S):
    """Медианы отношения ВНУТРИ пар «шард базы → шард головы». Описание, не контроль.

    Внутри пары обе машины закреплены, поэтому разброс МЕЖДУ медианами пар и есть
    видимая доля машин в общем размахе. Причинного вывода отсюда не делается.
    """
    fb, fl = by_file(base), by_file(later)
    pairs = {}
    for f in comparable_files(base, later):
        if fb[f] < min_baseline_s:
            continue
        key = (base.shard_of_file.get(f), later.shard_of_file.get(f))
        pairs.setdefault(key, []).append(fl[f] / fb[f])
    rows = [{"base_shard": k[0], "later_shard": k[1], "files": len(v),
             "median_ratio": statistics.median(v)}
            for k, v in pairs.items() if len(v) >= MIN_PAIR_FILES]
    rows.sort(key=lambda r: r["median_ratio"])
    return rows


def compare_sharded(base_records, later_records, comparable=True, why_not=()):
    """Сравнение двух шардированных прогонов. Род подорожания без контроля — НЕ ИЗМЕРЕН."""
    if not comparable:
        return {"verdict": "unmeasured:runs_not_comparable", "reason": "; ".join(why_not),
                "kind": "unmeasured:runs_not_comparable"}
    base, later = sharded_run(base_records), sharded_run(later_records)
    result = drift(base, later)
    result["shards"] = {
        "base": {"used": list(base.used), "excluded": [list(e) for e in base.excluded]},
        "later": {"used": list(later.used), "excluded": [list(e) for e in later.excluded]},
    }
    if result.get("verdict") == "measured":
        result["shard_pairs"] = shard_pair_spread(base, later)
    result["kind"] = read_as_work_or_environment(result, None)
    if result["kind"] == "unmeasured:no_same_commit_control":
        result["kind_reason"] = NO_CONTROL_REASON
    return result


def render_sharded(result, label_base, label_later):
    out = [render(result, label_base, label_later)]
    if result.get("kind_reason"):
        out.append("   почему без вывода: %s" % result["kind_reason"])
    pairs = result.get("shard_pairs") or []
    if pairs:
        out.append("   медиана ВНУТРИ пар «шард базы → шард головы» (пар с ≥ %d файлами: %d): "
                   "от ×%.3f до ×%.3f — описание доли машин, не контроль"
                   % (MIN_PAIR_FILES, len(pairs), pairs[0]["median_ratio"],
                      pairs[-1]["median_ratio"]))
    for side in ("base", "later"):
        for shard, why in (result.get("shards") or {}).get(side, {}).get("excluded", []):
            out.append("   исключён шард %s (%s): %s" % (shard, side, why))
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

    if result.get("verdict") != "measured" or str(result["kind"]).startswith("unmeasured"):
        return 2
    return 1 if result["kind"] != "within_runner_spread" else 0


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
