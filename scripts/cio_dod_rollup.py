#!/usr/bin/env python3
"""Сводный замер §50 приказа владельца «Portfolio CIO» — ВТОРОЙ приёмки.

Предмет — дыра, названная заказом G1056 п. 2 и не закрытая ни одним из
514 циклов, прошедших мимо приказа:

    «§50 («Definition of Done», 21 критерий) — ВТОРАЯ приёмка приказа,
     НЕ ИЗМЕРЕНА. Прибор §49 (`cio_acceptance_rollup.py`) сводит только §49.»

У приказа владельца **две** приёмки, и они разные. §49 («Acceptance criteria»)
перечисляет свойства СИСТЕМЫ и сведён прибором с ADR-810. §50 («Definition of
Done») перечисляет, что должно быть СДЕЛАНО, и начинается прямым запретом
владельца считать работу законченной по признакам «code implemented · tests
green · agent exists». Пятьдесят циклов мерили §10…§49; про §50 не было сказано
ни числа.

## Как прибор отвечает

1. **Население — из самой карточки приказа**, а не из списка в этом файле.
   Разбирается раздел `50. Definition of Done`, и в нём — ТОЛЬКО то, что стои́т
   ПОСЛЕ строки-анкера `Definition of Done:`. Строки ДО анкера есть
   ОТРИЦАТЕЛЬНАЯ преамбула владельца («не считать завершённым после…»), и
   зачесть их в население значило бы объявить критерием приёмки то, что владелец
   назвал её признаком-обманкой. Обе величины печатаются рядом: сколько взято и
   сколько ОТБРОШЕНО с названной причиной.

   Почему это важно числом: заказ G1056 п. 2 говорит «21 критерий», наивный счёт
   строк тела даёт 25, а честное население — 20. Три разных числа об одном
   разделе; перепечатанное число не отстаёт и не расходится — оно молча
   перестаёт быть правдой (`.claude/rules/site-numbers.md`). Поэтому «двадцать»
   здесь нигде не зашито: получит ТЗ владельца двадцать первый пункт — прибор
   ответит про двадцать один сам.

2. **Мерка — зарегистрированная проба**, объявившая себя мерой ЭТОГО критерия
   (`card_acceptance.probes_by_s50_criterion`, атрибут `s50_criterion`). Проба
   гоняется НАСТОЯЩАЯ, её вердикт берётся как есть.

3. **Критерий без пробы — ТРЕТИЙ ИСХОД** (инв. #17), а не ноль, не «не
   выполнено» и тем более не «выполнено». «Мерки сегодня нет» и «мера есть и
   говорит нет» — разные ответы, и чинятся они разным: первое объявляют, второе
   исправляют.

4. **Классы «НЕ ИЗМЕРЕНО» берутся у соседа, а не заводятся свои.**
   `cio_acceptance_rollup.unmeasured_class` — ЕДИНСТВЕННОЕ правило разбора
   (`мерки нет` · `НЕ О ТОМ ДЕРЕВЕ` · `по существу`), и своей копии здесь нет
   намеренно: две копии одной мерки расходятся молча (ADR-220), а разошлись бы
   они ровно там, где их читает человек, — в ИТОГЕ.

5. **Объявление, указывающее МИМО населения, — находка.** Проба претендует
   мерить критерий, которого у §50 нет (строку в ТЗ поправили, в объявлении
   опечатка), и молчание о ней означало бы, что критерий считается измеренным
   где-то не здесь.

## Чего прибор НЕ докладывает (назвать слепоту — часть замера)

* **Правду объявления.** `s50_criterion` говорит «проба претендует мерить этот
  критерий». Мерит ли она его на самом деле, решает её собственный контроль в
  обе стороны (`.claude/rules/acceptance.md`, п. 3), а не этот прибор.
* **Ближний промах.** У критерия без мерки рядом может лежать ПОХОЖАЯ проба с
  другим охватом. Прибор о ней молчит и обязан молчать: «мерка шире критерия» и
  «мерка есть» — разные ответы, и выдать второй за первый было бы ложным
  усилением. Каждый такой промах назван поимённо в ADR-1070, а не угадан кодом.
* **Соотношение с §49.** Пересечение требований двух приёмок владельца — это
  вопрос о СМЫСЛЕ двух его фраз, и решать его молча прибор не вправе.
* **Ничего не чинит.** ADVISORY: ни строки risk-логики, стоп-крана, аллокатора,
  живого трека или `landing/**`; только читает.

## Коды возврата

* **0** — население прочитано И каждый его член `satisfied`.
* **1** — население прочитано, но сводка не «всё выполнено»: есть
  `not_satisfied` и/или `unmeasured`. Обе тройки печатаются числом, поэтому код
  1 не двусмыслен.
* **2** — сводки НЕТ ВОВСЕ: карточка не найдена, раздел §50 или его анкер не
  разобраны, копии карточки разошлись. Про критерии при этом не сказано НИЧЕГО,
  и выдать это за «чисто» нельзя.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from spa_core.monitoring.card_acceptance import (  # noqa: E402
    NOT_SATISFIED,
    SATISFIED,
    TRACKER_REL,
    UNMEASURED,
    probe_tree_inputs,
    probes_by_s50_criterion,
    run_probe,
)

# Сосед по приёмке того же приказа. Ввозится ЦЕЛИКОМ, а не переписывается: у §49
# и §50 общие ответы на вопросы «из какой копии карточки читать», «какой класс у
# НЕ ИЗМЕРЕНО» и «состоялось ли сравнение копий». Разойдись эти ответы — две
# приёмки одного приказа давали бы несравнимые сводки.
import cio_acceptance_rollup as s49  # noqa: E402

Unmeasured = s49.Unmeasured

#: Карточка стоячего приказа владельца — носитель §50 (та же, что у §49).
CARD_REL = s49.CARD_REL

#: Заголовок раздела (дословно, как его написал владелец).
SECTION_HEAD = "50. Definition of Done"

#: Строка-анкер: население начинается ПОСЛЕ неё. До неё лежит отрицательная
#: преамбула владельца, и именно она есть причина, по которой анкер обязателен:
#: разбор «всё тело раздела» зачёл бы признаки-обманки в приёмку.
POPULATION_ANCHOR = "Definition of Done:"

#: Ветка доставки, с которой дочитывается вторая копия карточки.
ORIGIN_REF = s49.ORIGIN_REF


def parse_s50_criteria(text: str) -> dict:
    """Вынуть население §50 из тела карточки. Бросает :class:`Unmeasured` с причиной.

    Возврат — словарь: `criteria` (имена В ПОРЯДКЕ ТЗ), `rejected` (строки до
    анкера с причиной) и `body_lines` (сколько непустых строк в теле раздела
    всего). Порядок хранится намеренно: сводка в чужом порядке читается как
    другой документ. Отброшенное печатается намеренно: «отбросил три строки» и
    «их там не было» — разные наблюдения.
    """
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD]
    if not starts:
        raise Unmeasured(f"раздел {SECTION_HEAD!r} в карточке не найден — население "
                         f"§50 НЕ ПРОЧИТАНО")
    if len(starts) > 1:
        # Два раздела с одним номером — это не «возьмём первый»: у приказа стало
        # бы две разные приёмки, и выбор между ними сделал бы прибор молча.
        raise Unmeasured(f"раздел {SECTION_HEAD!r} встречается {len(starts)} раз "
                         f"(строки {', '.join(str(i + 1) for i in starts)}) — какую "
                         f"из приёмок приказа считать, НЕИЗВЕСТНО")

    start = starts[0]
    body: list[tuple[int, str]] = []
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if s49._SECTION_BREAK_RE.fullmatch(stripped) and body:
            break
        if s49._SECTION_BREAK_RE.fullmatch(stripped):
            continue
        body.append((i + 1, stripped))

    if not body:
        raise Unmeasured(f"раздел {SECTION_HEAD!r} найден на строке {start + 1}, но "
                         f"его тело ПУСТО — населения нет, а пустое население зелено "
                         f"по построению")

    anchors = [k for k, (_, line) in enumerate(body) if line == POPULATION_ANCHOR]
    if not anchors:
        # Анкера нет ⇒ границу «преамбула / приёмка» назвать нечем. Взять тело
        # целиком значило бы объявить критериями приёмки те признаки, которые
        # владелец перечислил как НЕДОСТАТОЧНЫЕ, — то есть ответить наоборот.
        raise Unmeasured(
            f"в теле раздела {SECTION_HEAD!r} (строки {body[0][0]}–{body[-1][0]}) нет "
            f"строки-анкера {POPULATION_ANCHOR!r} — границу между отрицательной "
            f"преамбулой владельца и самой приёмкой назвать НЕЧЕМ, население НЕ "
            f"ИЗМЕРЕНО")
    if len(anchors) > 1:
        raise Unmeasured(
            f"строка-анкер {POPULATION_ANCHOR!r} встречается в разделе "
            f"{len(anchors)} раз (строки "
            f"{', '.join(str(body[k][0]) for k in anchors)}) — где начинается "
            f"население, НЕИЗВЕСТНО")

    cut = anchors[0]
    rejected = [{"line": lineno, "text": line,
                 "reason": "стои́т ДО анкера — отрицательная преамбула владельца "
                           "(признак, который он назвал НЕдостаточным)"}
                for lineno, line in body[:cut]]
    tail = body[cut + 1:]
    if not tail:
        raise Unmeasured(
            f"анкер {POPULATION_ANCHOR!r} найден на строке {body[cut][0]}, но после "
            f"него в разделе НЕТ НИ ОДНОЙ строки — населения §50 нет, а пустое "
            f"население зелено по построению")

    names: list[str] = []
    for lineno, line in tail:
        if line in names:
            raise Unmeasured(f"строка {lineno}: критерий {line!r} объявлен в §50 "
                             f"дважды — население неоднозначно")
        names.append(line)

    return {"criteria": names, "rejected": rejected, "body_lines": len(body),
             "anchor_line": body[cut][0]}


def read_population(repo_root: str, *, ref: str = ORIGIN_REF,
                    card_rel: str = CARD_REL) -> dict:
    """Прочитать население §50 из ОБЕИХ копий карточки и свести их.

    Копии две (ADR-152: `nimbalyst-local/` в прод-дерево не синхронизируется), и
    расхождение §50 между ними означает, что у приказа две разные приёмки — это
    `Unmeasured`, а не «возьмём то, что под рукой».

    **Согласие копий доказательством дрейфа НЕ является** (урок ADR-504): когда
    `HEAD` И ЕСТЬ `ref`, а файл не правлен, копии совпадают ПО ПОСТРОЕНИЮ, и
    сравнение не способно найти расхождение в принципе. Поэтому сила сравнения
    печатается рядом с результатом (`comparison`), а не подразумевается.
    """
    read: list[tuple[str, dict]] = []
    problems: list[str] = []

    local_path = os.path.join(repo_root, card_rel)
    if os.path.isfile(local_path):
        try:
            with open(local_path, encoding="utf-8", errors="replace") as fh:
                read.append((f"дерево {repo_root}", parse_s50_criteria(fh.read())))
        except OSError as exc:
            problems.append(f"локальная копия не прочитана: {exc}")
        except Unmeasured as exc:
            problems.append(f"локальная копия: {exc}")
    else:
        problems.append(f"в дереве {repo_root} файла карточки нет")

    head, refsha = s49._head_sha(repo_root), s49._ref_sha(repo_root, ref)
    blob = s49._git_show(repo_root, ref, card_rel)
    if blob is None:
        problems.append(f"копия на `{ref}` не прочитана (нет git, нет ref или "
                        f"чтение прервалось)")
    else:
        try:
            read.append((ref, parse_s50_criteria(blob)))
        except Unmeasured as exc:
            problems.append(f"копия на `{ref}`: {exc}")

    if not read:
        raise Unmeasured("§50 не прочитан НИ ИЗ ОДНОЙ копии карточки: "
                         + " · ".join(problems))

    first_where, first = read[0]
    names = first["criteria"]
    for where, other in read[1:]:
        if other["criteria"] != names:
            raise Unmeasured(
                f"копии карточки дают РАЗНОЕ население §50: «{first_where}» — "
                f"{len(names)} критери(й/ев), «{where}» — "
                f"{len(other['criteria'])}; расхождение: "
                f"{sorted(set(names) ^ set(other['criteria'])) or 'порядок'}")

    edited = s49._card_is_edited(repo_root, card_rel)
    if len(read) < 2:
        comparison = ("сравнение копий НЕ СОСТОЯЛОСЬ: прочитана одна копия — "
                      + " · ".join(problems))
    elif edited is None:
        comparison = (f"СИЛА сравнения не измерена: правлен ли файл карточки в "
                      f"{repo_root}, спросить не вышло — совпадение копий могло быть "
                      f"тавтологией, а могло быть наблюдением")
    elif head and refsha and head == refsha and not edited:
        comparison = (f"сравнение копий ТАВТОЛОГИЧНО: HEAD и `{ref}` — один коммит "
                      f"{head[:9]}, файл карточки не правлен, расхождение здесь "
                      f"недостижимо по построению")
    else:
        comparison = (f"сравнение копий состоялось: HEAD {(head or '?')[:9]} против "
                      f"`{ref}` {(refsha or '?')[:9]}"
                      + (", файл карточки правлен" if edited else "")
                      + ", население совпало")

    return {"criteria": names, "rejected": first["rejected"],
            "body_lines": first["body_lines"], "anchor_line": first["anchor_line"],
            "sources": [w for w, _ in read], "comparison": comparison,
            "problems": problems}


def measure(repo_root: str, *, ref: str = ORIGIN_REF, card_rel: str = CARD_REL,
            measure_tree: str | None = None, data_dir: str | None = None,
            probe_runner=None) -> dict:
    """Свести §50: у каждого критерия — вердикт либо названная причина его отсутствия.

    `measure_tree` — дерево, О КОТОРОМ выносится вердикт (умолчание — дерево
    прибора). Оно доходит до пробы теми входами, которые она объявила, и **до
    какой пробы что дошло, ПЕЧАТАЕТСЯ у каждой строки** (`tree_inputs_reached`),
    а не подразумевается: вердикт пробы, читающей своё дерево, относится к ЭТОМУ
    дереву, и выдать его за вердикт о проде значило бы ответить на другой вопрос
    (`.claude/rules/deployment.md`, «половина инъекции — та же бомба»).
    """
    # Мерка разрешается В МОМЕНТ ЗОВА, а не умолчанием в сигнатуре: умолчание
    # связывается при ОПРЕДЕЛЕНИИ функции, поэтому подмена `run_probe` в модуле
    # до него не доходила бы — и контроль, думающий, что подменил мерку, на
    # самом деле мерил бы настоящую. Такой контроль зелен по построению.
    probe_runner = probe_runner or run_probe

    population = read_population(repo_root, ref=ref, card_rel=card_rel)
    names = population["criteria"]
    declared = probes_by_s50_criterion()

    orphan = {c: p for c, p in declared.items() if c not in names}

    rows = []
    for name in names:
        probes = declared.get(name) or []
        if not probes:
            rows.append({"criterion": name, "probe": None, "verdict": UNMEASURED,
                         "detail": "машинной пробы, объявившей себя мерой этого "
                                   "критерия §50, в реестре НЕТ — вердикт сегодня "
                                   "взять неоткуда",
                         "tree_inputs_declared": None,
                         "tree_inputs_reached": None})
            continue
        if len(probes) > 1:
            rows.append({"criterion": name, "probe": None, "verdict": UNMEASURED,
                         "detail": f"критерий объявлен мерой сразу у {len(probes)} проб "
                                   f"({', '.join(probes)}) — выбрать из них молча "
                                   f"значило бы спрятать столкновение объявлений",
                         "tree_inputs_declared": None,
                         "tree_inputs_reached": None})
            continue
        accepted = probe_tree_inputs(probes[0])
        if measure_tree or data_dir:
            # ОДНА копия правила: что предложено, то и напечатано дошедшим
            # (ADR-220 — вторая копия мерки соврала бы о достижимости).
            offered = {
                "repo_root": measure_tree,
                "data_dir": data_dir or (os.path.join(measure_tree, "data")
                                         if measure_tree else None),
                "tracker_dir": (os.path.join(measure_tree, TRACKER_REL)
                                if measure_tree else None),
            }
            kw = {k: offered.get(k) for k in accepted}
            verdict, detail = probe_runner(probes[0], **kw)
            reached = [k for k in accepted if kw.get(k)]
        else:
            verdict, detail = probe_runner(probes[0])
            reached = None
        rows.append({"criterion": name, "probe": probes[0], "verdict": verdict,
                     "detail": detail, "tree_inputs_declared": list(accepted),
                     "tree_inputs_reached": reached})

    counts = {SATISFIED: 0, NOT_SATISFIED: 0, UNMEASURED: 0}
    unmeasured_classes = {s49.UNMEASURED_NO_MEASURE: 0,
                          s49.UNMEASURED_TREE_NOT_REACHED: 0,
                          s49.UNMEASURED_IN_SUBJECT_TREE: 0}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
        # Класс пишется в строку КАЖДОГО критерия, а не только неизмеренного:
        # `None` у измеренной строки есть ответ «вопрос не стои́т», и отличим он
        # от отсутствия поля, то есть от «класс не считали вовсе».
        row["unmeasured_class"] = s49.unmeasured_class(row)
        if row["unmeasured_class"] is not None:
            unmeasured_classes[row["unmeasured_class"]] += 1

    return {"state": "measured", "criteria": names, "rows": rows,
            "counts": counts, "unmeasured_classes": unmeasured_classes,
            "rejected": population["rejected"],
            "body_lines": population["body_lines"],
            "anchor_line": population["anchor_line"],
            "orphan_declarations": orphan,
            "sources": population["sources"],
            "comparison": population["comparison"],
            "problems": population["problems"],
            "measure_tree": measure_tree or repo_root,
            "data_dir": data_dir,
            # Сборность судится против ДЕЙСТВУЮЩЕГО дерева (`measure_tree or
            # repo_root`), а не против названного флагом. Условие «обязаны быть
            # заданы ОБА флага» молчало бы ровно в самом частом зове: из worktree
            # живого `data/` нет по построению, поэтому `--data-dir` прод-дерева
            # передают БЕЗ `--measure-tree` — и сборность налицо, а признак был
            # бы ложно пуст (тот же класс, что «половина инъекции» в
            # `.claude/rules/deployment.md`).
            "split_tree": bool(data_dir and os.path.abspath(data_dir)
                               != os.path.abspath(os.path.join(
                                   measure_tree or repo_root, "data")))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--repo-root", default=os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))),
        help="дерево, из которого читается карточка приказа")
    ap.add_argument("--ref", default=ORIGIN_REF,
                    help="ветка, с которой дочитывается вторая копия карточки")
    ap.add_argument("--measure-tree", default=None,
                    help="дерево, О КОТОРОМ выносится вердикт (умолчание — дерево "
                         "прибора)")
    ap.add_argument("--data-dir", default=None,
                    help="каталог живого data/ для проб, объявивших такой вход")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    try:
        report = measure(args.repo_root, ref=args.ref,
                         measure_tree=args.measure_tree, data_dir=args.data_dir)
    except Unmeasured as exc:
        if args.json:
            print(json.dumps({"state": "unmeasured", "reason": str(exc)},
                             ensure_ascii=False, indent=2))
        else:
            print(f"НЕ ИЗМЕРЕНО: {exc}")
            print("сводки §50 нет вовсе — про критерии ВТОРОЙ приёмки приказа НЕ "
                  "СКАЗАНО НИЧЕГО")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["counts"][SATISFIED] == len(report["criteria"]) else 1

    counts = report["counts"]
    print(f"§50 приказа «Portfolio CIO» — ВТОРАЯ приёмка, сводный замер "
          f"({len(report['criteria'])} критери(й/ев), источники: "
          f"{', '.join(report['sources'])})")
    print(f"  вердикт выносится о дереве: {report['measure_tree']}")
    if report["split_tree"]:
        print(f"  ⚠️  СБОРНЫЙ ЗАМЕР: поверхности из {report['measure_tree']}, "
              f"артефакты из {report['data_dir']} — это вердикт НИ ОБ ОДНОМ "
              f"существующем дереве")
    print(f"  {report['comparison']}")
    for problem in report["problems"]:
        print(f"  ⚠️  {problem}")
    print(f"  население взято ПОСЛЕ анкера {POPULATION_ANCHOR!r} (строка "
          f"{report['anchor_line']}): непустых строк в теле раздела "
          f"{report['body_lines']}, в население вошло {len(report['criteria'])}, "
          f"ОТБРОШЕНО {len(report['rejected'])}")
    for bad in report["rejected"]:
        print(f"      ⊘ строка {bad['line']}: {bad['text']!r} — {bad['reason']}")
    print()

    marks = {SATISFIED: "✅", NOT_SATISFIED: "❌", UNMEASURED: "⚠️ "}
    for row in report["rows"]:
        probe = row["probe"] or "пробы нет"
        tag = ""
        if row.get("unmeasured_class"):
            tag = f"  [{s49.UNMEASURED_CLASS_RU[row['unmeasured_class']]}]"
        print(f"  {marks[row['verdict']]}  {row['criterion']}  [{probe}]{tag}")
        print(f"      {row['detail']}")
        if row.get("tree_inputs_declared") is not None:
            print(f"      входы дерева: объявлены "
                  f"{row['tree_inputs_declared'] or '—'}, дошли "
                  f"{row['tree_inputs_reached'] if row['tree_inputs_reached'] is not None else 'дерево не объявлялось'}")
    print()
    print(f"ИТОГ: ВЫПОЛНЕНО {counts[SATISFIED]} · НЕ ВЫПОЛНЕНО "
          f"{counts[NOT_SATISFIED]} · НЕ ИЗМЕРЕНО {counts[UNMEASURED]} "
          f"из {len(report['criteria'])}")
    if counts[UNMEASURED]:
        print("  из «НЕ ИЗМЕРЕНО»: " + " · ".join(
            f"{s49.UNMEASURED_CLASS_RU[k]} {v}"
            for k, v in report["unmeasured_classes"].items() if v))
    if report["orphan_declarations"]:
        for crit, probes in sorted(report["orphan_declarations"].items()):
            print(f"  ❗ОБЪЯВЛЕНИЕ МИМО НАСЕЛЕНИЯ: пробы {', '.join(probes)} "
                  f"объявили мерой критерий {crit!r}, которого в §50 карточки НЕТ")
    print("ADVISORY: прибор только ЧИТАЕТ — ни risk-логика, ни стоп-кран, ни "
          "аллокатор, ни живой трек, ни landing/ им не трогаются")
    return 0 if counts[SATISFIED] == len(report["criteria"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
