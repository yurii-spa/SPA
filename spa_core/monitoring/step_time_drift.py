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
from typing import NamedTuple

from spa_core.monitoring.step_time_census import READ_OK, by_file, census_from_path

#: Меньше этого числа сопоставимых файлов — квартили считать не на чем.
MIN_COMPARABLE_FILES = 100

#: Файлы дешевле этого в опорном прогоне из отношений исключаются: на десятых долях
#: секунды отношение меряет разрешение часов, а не стоимость.
MIN_BASELINE_S = 1.0


class Profile(NamedTuple):
    """СЕКУНДЫ и ЧИСЛО СЛУЧАЕВ по файлам + чем это чтение было получено.

    Профиль появился потому, что прогон бывает **СОСТАВНЫМ**: контрольный прогон
    (`.github/workflows/ci-control.yml`) режет ТО ЖЕ население на 12 шардов, и
    потоковая запись у каждого шарда своя (`ctl-shard-<N>/stream.jsonl`).

    **Сливать СОБЫТИЯ двенадцати записей в одну ЗАПРЕЩЕНО, и это не вкусовщина.**
    `span` случая определён как «от своего старта до старта СЛЕДУЮЩЕГО», а шарды
    идут ПАРАЛЛЕЛЬНО на разных раннерах: у склеенной записи это число мерило бы
    чередование раннеров, а не стоимость теста. Файлы же у шардов РАЗНЫЕ по
    построению (план режет население по ФАЙЛУ), поэтому складывать по ФАЙЛУ
    можно — и это единственное сложение, которое профиль делает. Файл, пришедший
    из ДВУХ частей, объявляется в `files_in_two_parts`: сложить его секунды
    значило бы молча смешать два раннера в одном числе.

    `span_is_wall` — объявление РОДА числа `span_s`, а не украшение. У одной
    записи это стена сессии; у составного прогона — СУММА размахов частей, то
    есть машинные секунды, которых на стене не было никогда. Печатать их словом
    «стена» значило бы соврать в двенадцать раз.
    """

    read: str
    reason: str
    seconds: dict                   # файл → секунды
    cases: dict                     # файл → число случаев
    n_cases: int
    span_s: float
    ended: bool
    span_is_wall: bool = True
    parts: int = 1
    parts_read: int = 1
    parts_unread: tuple = ()        # (метка, причина) по каждой непрочитанной части
    files_in_two_parts: tuple = ()
    #: Сколько СЕССИЙ лежит в записях частей. Больше, чем прочитанных частей,
    #: означает ДОИГРЫВАНИЕ (`ci_control.run-shard --max-resumes 3` пишет в ТУ ЖЕ
    #: запись), и тогда «случаев в записи» БОЛЬШЕ работы: часть случаев записана
    #: дважды. Без этого числа рост населения читался бы как рост работы.
    sessions: int = 1
    torn_lines: int = 0


def profile_of_census(census) -> Profile:
    """Профиль ОДНОЙ записи. Нечитаемая запись несёт свою причину дальше."""
    if census.read != READ_OK:
        return Profile(read=census.read, reason=census.reason, seconds={}, cases={},
                       n_cases=0, span_s=0.0, ended=False, parts=1, parts_read=0,
                       parts_unread=((census.read, census.reason),))
    cases: dict = {}
    for case in census.cases:
        cases[case.file] = cases.get(case.file, 0) + 1
    return Profile(read=READ_OK, reason="", seconds=dict(by_file(census)), cases=cases,
                   n_cases=len(census.cases), span_s=census.span_s, ended=census.ended,
                   sessions=census.sessions_in_record, torn_lines=census.torn_lines)


def profile_of_parts(parts) -> Profile:
    """Профиль СОСТАВНОГО прогона: `parts` = последовательность (метка, запись).

    Исходы РАЗЛИЧИМЫ (инв. #17): ни одна часть не прочитана ⇒ `read` называет
    причину, а не отдаёт нули; часть прочитана, часть нет ⇒ профиль ЕСТЬ, и
    непрочитанные НАЗВАНЫ поимённо (`parts_unread`), потому что их файлы просто
    не попадут в сопоставимые — молча и без следа, если о них не сказать.
    """
    parts = list(parts)
    if not parts:
        return Profile(read="parts_absent", reason="частей прогона не передано ни одной",
                       seconds={}, cases={}, n_cases=0, span_s=0.0, ended=False,
                       span_is_wall=False, parts=0, parts_read=0)
    seconds: dict = {}
    cases: dict = {}
    owner: dict = {}
    twice: list = []
    unread: list = []
    span = 0.0
    n_cases = 0
    sessions = 0
    torn = 0
    ended = True
    for label, census in parts:
        if census.read != READ_OK:
            unread.append((str(label), census.reason))
            ended = False
            continue
        span += census.span_s
        n_cases += len(census.cases)
        sessions += census.sessions_in_record
        torn += census.torn_lines
        ended = ended and census.ended
        for case in census.cases:
            cases[case.file] = cases.get(case.file, 0) + 1
            if owner.setdefault(case.file, label) != label and case.file not in twice:
                twice.append(case.file)
        for name, value in by_file(census).items():
            seconds[name] = seconds.get(name, 0.0) + value
    read_ok = len(parts) - len(unread)
    if not read_ok:
        return Profile(read="parts_unreadable",
                       reason="ни одна часть прогона не прочитана: "
                              + "; ".join("%s — %s" % row for row in unread[:3]),
                       seconds={}, cases={}, n_cases=0, span_s=0.0, ended=False,
                       span_is_wall=False, parts=len(parts), parts_read=0,
                       parts_unread=tuple(unread))
    return Profile(read=READ_OK, reason="", seconds=seconds, cases=cases,
                   n_cases=n_cases, span_s=span, ended=ended, span_is_wall=False,
                   parts=len(parts), parts_read=read_ok, parts_unread=tuple(unread),
                   files_in_two_parts=tuple(sorted(twice)),
                   sessions=sessions, torn_lines=torn)


def comparable_in(base: Profile, later: Profile) -> set:
    """Файлы, у которых ЧИСЛО случаев в обоих прогонах одинаково.

    Равенство числа случаев — и есть определение «работа та же». Файл, где тест
    добавили или сняли, из отношений исключается: в нём смешаны оба рода.
    """
    return {f for f, n in base.cases.items() if later.cases.get(f) == n}


def comparable_files(base, later):
    """То же для двух ЗАПИСЕЙ — дверь одна, профиль у неё внутри."""
    return comparable_in(profile_of_census(base), profile_of_census(later))


def drift(base, later, min_baseline_s=MIN_BASELINE_S):
    """Распределение отношения «позже / раньше» по двум ЗАПИСЯМ."""
    return drift_profiles(profile_of_census(base), profile_of_census(later),
                          min_baseline_s)


def drift_profiles(base: Profile, later: Profile, min_baseline_s=MIN_BASELINE_S):
    """То же по двум ПРОФИЛЯМ — составной прогон сравнивается этой дверью."""
    if base.read != READ_OK:
        return {"verdict": "unmeasured:baseline_%s" % base.read, "reason": base.reason}
    if later.read != READ_OK:
        return {"verdict": "unmeasured:later_%s" % later.read, "reason": later.reason}

    fb, fl = base.seconds, later.seconds
    shared = comparable_in(base, later)
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
        "cases_base": base.n_cases,
        "cases_later": later.n_cases,
        "case_growth": ((later.n_cases - base.n_cases) / base.n_cases
                        if base.n_cases else None),
        "span_base_s": base.span_s,
        "span_later_s": later.span_s,
        "base_ended": base.ended,
        "later_ended": later.ended,
        # Род числа `span_*` объявлен РЯДОМ с ним: у составного прогона это сумма
        # размахов частей, а не стена, и читатель обязан увидеть это в документе,
        # а не узнать из устной договорённости.
        "span_is_wall": base.span_is_wall and later.span_is_wall,
        "parts_base": base.parts,
        "parts_later": later.parts,
        "parts_read_base": base.parts_read,
        "parts_read_later": later.parts_read,
        "parts_unread_base": list(base.parts_unread),
        "parts_unread_later": list(later.parts_unread),
        # Доигранный шард пишет в ТУ ЖЕ запись, поэтому «случаев» и «работы» —
        # разные числа, и рост первого без второго числа читался бы как рост
        # работы. Отношения по файлам от этого защищены (у доигранного файла
        # число случаев перестаёт совпадать и он выпадает из сопоставимых), а
        # печатаемый рост населения — НЕТ.
        "sessions_base": base.sessions,
        "sessions_later": later.sessions,
        "resumed_base": base.sessions > base.parts_read,
        "resumed_later": later.sessions > later.parts_read,
        "files_in_two_parts": list(base.files_in_two_parts) + list(later.files_in_two_parts),
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

    # Род числа называется ВМЕСТЕ с числом: у составного прогона (12 шардов) это
    # сумма размахов частей, и слово «стена» было бы ложью в двенадцать раз.
    wall = result.get("span_is_wall", True)
    for tag, key, ended in (("раньше", "span_base_s", "base_ended"),
                            ("позже ", "span_later_s", "later_ended")):
        out.append("   %s %s: %.1f мин%s" % (
            "стена" if wall else "машинных минут (Σ частей, НЕ стена)",
            tag, result[key] / 60.0,
            "" if result[ended] else "  (НИЖНЯЯ ГРАНИЦА — сессия оборвана)"))
    if not wall:
        out.append("   частей прочитано: раньше %s/%s · позже %s/%s" % (
            result.get("parts_read_base"), result.get("parts_base"),
            result.get("parts_read_later"), result.get("parts_later")))
        for side in ("parts_unread_base", "parts_unread_later"):
            for label, why in (result.get(side) or []):
                out.append("   ❗часть НЕ ПРОЧИТАНА (%s): %s — %s"
                           % (side.split("_")[-1], label, why))
        if result.get("files_in_two_parts"):
            out.append("   ❗файл пришёл из ДВУХ частей (%d): %s"
                       % (len(result["files_in_two_parts"]),
                          ", ".join(result["files_in_two_parts"][:3])))
    growth = result.get("case_growth")
    if result.get("resumed_base") or result.get("resumed_later"):
        out.append("   ❗шард ДОИГРЫВАЛСЯ: сессий в записях %s → %s при частях %s → %s "
                   "— «случаев» БОЛЬШЕ работы, часть записана дважды"
                   % (result.get("sessions_base"), result.get("sessions_later"),
                      result.get("parts_read_base"), result.get("parts_read_later")))
    out.append("   случаев В ЗАПИСИ %d → %d  (%s)" % (
        result["cases_base"], result["cases_later"],
        "НЕ ИЗМЕРЕНО: случаев раньше ноль" if growth is None
        else "%+.1f %%" % (100.0 * growth)))
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

    return exit_code(result)


#: Исходы кода возврата ОБЪЯВЛЕНЫ, а не выведены из знака. Разница измерена
#: подключением (ADR-896): прежняя строка возвращала **1** («находка») и тогда,
#: когда род подорожания НЕ ИЗМЕРЕН — `kind="unmeasured:no_same_commit_control"`
#: не равен `within_runner_spread`, и ветка «иначе 1» объявляла отсутствие
#: контроля находкой. Инв. #17 требует ТРИ различимых исхода, и у кода возврата
#: их теперь три: 0 — измерено, находки нет · 1 — измерено, находка НАЗВАНА ·
#: 2 — НЕ ИЗМЕРЕНО (ни распределение, ни род).
CODE_OK, CODE_FINDING, CODE_UNMEASURED = 0, 1, 2

#: Какой РОД подорожания есть находка. Перечень закрытый: род вне него (в том
#: числе любой `unmeasured:*`) находкой не становится молча.
FINDING_KINDS = ("environment_beyond_runner_spread", "work_changed")


def exit_code(result) -> int:
    """Три исхода, и ни один не выдаётся за другой (инв. #17)."""
    if result.get("verdict") != "measured":
        return CODE_UNMEASURED
    kind = result.get("kind")
    if isinstance(kind, str) and kind.startswith("unmeasured"):
        return CODE_UNMEASURED
    if kind in FINDING_KINDS and (result.get("median_ratio") or 0.0) > 1.0:
        return CODE_FINDING
    return CODE_OK


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
