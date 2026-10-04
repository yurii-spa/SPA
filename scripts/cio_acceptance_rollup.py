#!/usr/bin/env python3
"""Сводный замер §49 приказа владельца «Portfolio CIO»: сколько критериев ВЫПОЛНЕНО.

Предмет — дыра, которую одиннадцать циклов подряд (#710…#722) называли своими
словами в хвосте карточки и ни один не закрыл:

    «Все тринадцать критериев §49 измерены; сводного замера
     "сколько из тринадцати ВЫПОЛНЕНО" по-прежнему не делал никто.»

Каждый критерий мерил СВОЙ цикл и записывал вердикт прозой в СВОЙ ADR
(ADR-241…245, ADR-480, ADR-484…491). Тринадцать вердиктов прозой — это тринадцать
утверждений сессий, которых уже нет; сложить их в число, перечитав тексты, значило
бы произвести ровно тот дефект, против которого написано правило о числах:
**перепечатанное число не отстаёт и не расходится — оно молча перестаёт быть
правдой** (`.claude/rules/site-numbers.md`). Поэтому прибор ничего не перечитывает
из ADR. Он спрашивает заново.

## Как он отвечает

1. **Население — из самой карточки приказа**, а не из списка в этом файле.
   Разбирается раздел `49. Acceptance criteria` и берутся его заголовки. Число
   критериев — ЗАМЕР; «тринадцать» здесь нигде не зашито, и если ТЗ владельца
   завтра получит четырнадцатый пункт, прибор ответит про четырнадцать сам.
2. **Мерка — зарегистрированная проба**, объявившая себя мерой этого критерия
   (`card_acceptance.probes_by_s49_criterion`). Проба гоняется НАСТОЯЩАЯ, её
   вердикт берётся как есть.
3. **Критерий без пробы — ТРЕТИЙ ИСХОД**, а не ноль, не «не выполнено» и тем более
   не «выполнено» (инв. #17). «Меры сегодня нет» и «мера есть и говорит нет» —
   разные ответы, и чинятся они разным: первое пишут, второе исправляют.
4. **У каждого «НЕ ИЗМЕРЕНО» названа ЦЕНА** (заказ G93 п. 1,
   `spa_core/monitoring/s49_criterion_price.py`). Десять одинаковых `НЕ ИЗМЕРЕНО`
   читаются как десять одинаковых дыр, а это неверно: у одних артефакт уже живёт,
   свеж и объявлен в конституции — не хватает ОДНОГО поля; у других артефакта нет
   вовсе — не хватает РЕШЕНИЯ, какой артефакт есть мера. Слить их в одно слово
   значило бы повторить дефект инв. #17 этажом выше.

## Чего прибор НЕ докладывает (назвать слепоту — часть замера)

* **Правду объявления.** `s49_criterion` говорит «проба претендует мерить этот
  критерий». Мерит ли она его на самом деле, решает её собственный контроль в обе
  стороны (`.claude/rules/acceptance.md`, п. 3), а не этот прибор.
* **Полноту критерия.** Проба может мерить УЖЕ критерия: `no_regression_tests_pass`
  спрашивает объявленные поверхности, а не весь набор. Зазор назван у пробы.
* **Ничего не чинит.** ADVISORY: ни строки risk-логики, стоп-крана, аллокатора,
  живого трека или `landing/**`; только читает.

## Коды возврата

* **0** — население прочитано И каждый его член `satisfied`.
* **1** — население прочитано, но сводка не «все выполнено»: есть `not_satisfied`
  и/или `unmeasured`. Обе тройки печатаются числом, поэтому код 1 не двусмыслен.
* **2** — сводки НЕТ ВОВСЕ: карточка не найдена, раздел §49 не разобран, копии
  разошлись. Про критерии при этом не сказано НИЧЕГО, и выдать это за «чисто»
  нельзя.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spa_core.monitoring.card_acceptance import (  # noqa: E402
    NOT_SATISFIED,
    SATISFIED,
    TRACKER_REL,
    UNMEASURED,
    probe_tree_inputs,
    probes_by_s49_criterion,
    run_probe,
)
from spa_core.monitoring import card_acceptance as _card_acceptance  # noqa: E402
from spa_core.monitoring import probe_verdict_authorship as authorship  # noqa: E402
from spa_core.monitoring import s49_criterion_price as price_meter  # noqa: E402
from spa_core.monitoring import s49_verdict_addressee as addressee_meter  # noqa: E402

#: Карточка стоячего приказа владельца — носитель §49.
CARD_REL = "nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md"

#: Заголовок раздела приёмки в теле ТЗ (дословно, как его написал владелец).
SECTION_HEAD = "49. Acceptance criteria"

#: Ветка доставки, с которой дочитывается вторая копия карточки.
ORIGIN_REF = "origin/main"

#: Заголовок критерия: короткая латинская строка БЕЗ точки на конце. Описание под
#: ним точкой заканчивается всегда — на этом и держится разбор, и он проверяется
#: не формой, а СТРОГИМ ЧЕРЕДОВАНИЕМ (заголовок → описание → заголовок → …):
#: строка, выпавшая из чередования, обрывает разбор с причиной, а не молча
#: пропускается. Разбор, умеющий «пропустить непонятное», врал бы тихо.
_HEADING_RE = re.compile(r"[A-Z][A-Za-z][A-Za-z -]{0,40}\Z")

#: Конец раздела: разделитель ТЗ, пустая строка или заголовок следующего раздела.
_SECTION_BREAK_RE = re.compile(r"\A(?:\s*|⸻|\d+\.\s.*)\Z")


class Unmeasured(Exception):
    """Сводки нет вовсе. Несёт причину, которую обязан напечатать вызывающий."""


def _is_heading(line: str) -> bool:
    return bool(_HEADING_RE.fullmatch(line)) and not line.endswith(".")


def parse_s49_criteria(text: str) -> list[str]:
    """Вынуть население §49 из тела карточки. Бросает :class:`Unmeasured` с причиной.

    Возврат — имена критериев В ПОРЯДКЕ ТЗ. Порядок хранится намеренно: сводка,
    напечатанная в чужом порядке, читается как другой документ.
    """
    lines = text.split("\n")
    starts = [i for i, ln in enumerate(lines) if ln.strip() == SECTION_HEAD]
    if not starts:
        raise Unmeasured(f"раздел {SECTION_HEAD!r} в карточке не найден — население "
                         f"§49 НЕ ПРОЧИТАНО")
    if len(starts) > 1:
        # Два раздела с одним номером — это не «возьмём первый»: у приказа стало
        # бы два разных населения, и выбор между ними сделал бы прибор молча.
        raise Unmeasured(f"раздел {SECTION_HEAD!r} встречается {len(starts)} раз "
                         f"(строки {', '.join(str(i + 1) for i in starts)}) — какое "
                         f"из населений приказа считать, НЕИЗВЕСТНО")

    start = starts[0]
    body: list[tuple[int, str]] = []
    for i in range(start + 1, len(lines)):
        raw = lines[i]
        if _SECTION_BREAK_RE.fullmatch(raw.strip()) and body:
            break
        if _SECTION_BREAK_RE.fullmatch(raw.strip()):
            continue
        body.append((i + 1, raw.strip()))

    if not body:
        raise Unmeasured(f"раздел {SECTION_HEAD!r} найден на строке {start + 1}, но его "
                         f"тело ПУСТО — населения нет, а пустое население зелено по "
                         f"построению")

    # Вводная строка ТЗ («Работа считается выполненной только когда доказано
    # следующее.») заголовком не является; пропускаем ВСЁ до первого заголовка, а
    # дальше требуем строгого чередования.
    idx = 0
    while idx < len(body) and not _is_heading(body[idx][1]):
        idx += 1
    if idx >= len(body):
        raise Unmeasured(f"в теле раздела {SECTION_HEAD!r} (строки "
                         f"{body[0][0]}–{body[-1][0]}) нет НИ ОДНОГО заголовка "
                         f"критерия — разбор не состоялся")

    names: list[str] = []
    expect_heading = True
    for lineno, line in body[idx:]:
        if expect_heading:
            if not _is_heading(line):
                raise Unmeasured(
                    f"строка {lineno} ожидалась заголовком критерия, а прочитана как "
                    f"описание: {line!r} — чередование §49 нарушено, население НЕ "
                    f"ИЗМЕРЕНО")
            if line in names:
                raise Unmeasured(f"строка {lineno}: критерий {line!r} объявлен в §49 "
                                 f"дважды — население неоднозначно")
            names.append(line)
        elif _is_heading(line):
            raise Unmeasured(
                f"строка {lineno}: у критерия {names[-1]!r} нет строки описания — "
                f"следом сразу заголовок {line!r}; чередование §49 нарушено")
        expect_heading = not expect_heading

    if expect_heading is False:
        raise Unmeasured(f"последний критерий {names[-1]!r} остался без описания — "
                         f"раздел §49 оборван, население НЕ ИЗМЕРЕНО")
    return names


def _git_show(repo_root: str, ref: str, rel: str) -> str | None:
    try:
        out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=repo_root,
                             capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", errors="replace")


def _head_sha(repo_root: str) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root,
                             capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode().strip() if out.returncode == 0 else None


def _ref_sha(repo_root: str, ref: str) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", ref], cwd=repo_root,
                             capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.decode().strip() if out.returncode == 0 else None


def _card_is_edited(repo_root: str, rel: str) -> bool | None:
    """Правлен ли файл карточки относительно `HEAD`. `None` — спросить не вышло.

    Нужен ИМЕННО этот вопрос, а не «HEAD == ref»: сравнение копий тавтологично
    только когда ОБА условия вместе — ветка та же И файл не трогали. Правленый
    файл делает сравнение настоящим даже при `HEAD == ref`, и объявить его
    тавтологичным значило бы отказаться от состоявшегося наблюдения.
    """
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", rel],
                             cwd=repo_root, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return bool(out.stdout.decode("utf-8", errors="replace").strip())


def read_population(repo_root: str, *, ref: str = ORIGIN_REF,
                    card_rel: str = CARD_REL) -> dict:
    """Прочитать население §49 из ОБЕИХ копий карточки и свести их.

    Копии две (ADR-152: `nimbalyst-local/` в прод-дерево не синхронизируется), и
    расхождение §49 между ними означает, что у приказа два разных населения —
    это `Unmeasured`, а не «возьмём то, что под рукой».

    **Согласие копий доказательством дрейфа НЕ является** (урок ADR-504): когда
    `HEAD` И ЕСТЬ `ref`, а файл не правлен, копии совпадают ПО ПОСТРОЕНИЮ, и
    сравнение не способно найти расхождение в принципе. Поэтому сила сравнения
    печатается рядом с результатом (`comparison`), а не подразумевается: читатель
    видит, был ли вопрос вообще задан.
    """
    read: list[tuple[str, list[str]]] = []
    problems: list[str] = []

    local_path = os.path.join(repo_root, card_rel)
    if os.path.isfile(local_path):
        try:
            with open(local_path, encoding="utf-8", errors="replace") as fh:
                read.append((f"дерево {repo_root}", parse_s49_criteria(fh.read())))
        except OSError as exc:
            problems.append(f"локальная копия не прочитана: {exc}")
        except Unmeasured as exc:
            problems.append(f"локальная копия: {exc}")
    else:
        problems.append(f"в дереве {repo_root} файла карточки нет")

    head, refsha = _head_sha(repo_root), _ref_sha(repo_root, ref)
    blob = _git_show(repo_root, ref, card_rel)
    if blob is None:
        problems.append(f"копия на `{ref}` не прочитана (нет git, нет ref или "
                        f"чтение прервалось)")
    else:
        try:
            read.append((ref, parse_s49_criteria(blob)))
        except Unmeasured as exc:
            problems.append(f"копия на `{ref}`: {exc}")

    if not read:
        raise Unmeasured("§49 не прочитан НИ ИЗ ОДНОЙ копии карточки: "
                         + " · ".join(problems))

    names = read[0][1]
    for where, other in read[1:]:
        if other != names:
            raise Unmeasured(
                f"копии карточки дают РАЗНОЕ население §49: «{read[0][0]}» — "
                f"{len(names)} критери(й/ев), «{where}» — {len(other)}; "
                f"расхождение: {sorted(set(names) ^ set(other)) or 'порядок'}")

    edited = _card_is_edited(repo_root, card_rel)
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

    return {"criteria": names, "sources": [w for w, _ in read],
            "comparison": comparison, "problems": problems}


def measure(repo_root: str, *, ref: str = ORIGIN_REF, card_rel: str = CARD_REL,
            measure_tree: str | None = None, data_dir: str | None = None,
            probe_runner=None, now=None) -> dict:
    """Свести §49: у каждого критерия — вердикт либо названная причина его отсутствия.

    `measure_tree` — дерево, О КОТОРОМ выносится вердикт (умолчание — дерево
    прибора). Оно доходит до пробы теми входами, которые она объявила
    (`repo_root`, `data_dir`), и **до какой пробы что дошло, ПЕЧАТАЕТСЯ у каждой
    строки** (`tree_inputs_reached`), а не подразумевается: вердикт пробы,
    читающей своё дерево, относится к ЭТОМУ дереву, и выдать его за вердикт о
    проде значило бы ответить на другой вопрос (`.claude/rules/deployment.md`,
    «половина инъекции — та же бомба»).

    `data_dir` отдельно от `measure_tree` — форма НАМЕРЕННО неудобная и громкая.
    Она нужна затем, чтобы РАЗРЫВ можно было предъявить командой, а не пересказом:
    поверхности владельца живут в дереве с `landing/`, артефакты — в прод-дереве с
    живым `data/`, и `landing/` в прод-дерево не синхронизируется (ADR-152). Сводка,
    собранная из двух деревьев, есть вердикт НИ ОБ ОДНОМ существующем дереве, и
    прибор говорит это вслух (`split_tree`), а не подмешивает молча.
    """
    # Мерка разрешается В МОМЕНТ ЗОВА, а не умолчанием в сигнатуре: умолчание
    # связывается при ОПРЕДЕЛЕНИИ функции, поэтому подмена `run_probe` в модуле
    # до него не доходила бы — и контроль, думающий, что подменил мерку, на
    # самом деле мерил настоящую. Такой контроль зелен по построению.
    probe_runner = probe_runner or run_probe

    # Род вердикта читается НАД ТЕМ ЖЕ файлом, из которого пришли исполняемые
    # пробы (`card_acceptance.__file__`), а НЕ над `--repo-root`. Разница
    # существенна: пробы приходят из `sys.path`, карточка — из названного
    # дерева, и прочитать род из второго значило бы судить о паре «реестр одного
    # дерева × тело другого» — ровно тот дефект, который сводка про себя уже
    # говорит вслух словом `split_tree`.
    authorship_problem = None
    authorship_report = None
    try:
        authorship_report = authorship.measure(
            source=getattr(_card_acceptance, "__file__", None))
    except authorship.Unmeasured as exc:
        # Род НЕ ИЗМЕРЕН — это третий исход, а не «своя мера»: сводка обязана
        # сказать читателю, что адресата красной строки назвать нечем.
        authorship_problem = str(exc)

    population = read_population(repo_root, ref=ref, card_rel=card_rel)
    names = population["criteria"]
    declared = probes_by_s49_criterion()

    # Объявление, указывающее МИМО населения, — находка, а не тихий ноль: проба
    # претендует мерить критерий, которого у приказа нет (переименовали в ТЗ,
    # опечатались в объявлении), и молчание о ней означало бы, что критерий
    # считается измеренным где-то не здесь.
    orphan = {c: p for c, p in declared.items() if c not in names}

    rows = []
    for name in names:
        probes = declared.get(name) or []
        if not probes:
            # `priceable` — не украшение строки, а её ОТБОР в замер цены. Цена
            # (G93 п. 1) отвечает на вопрос «чего не хватает, чтобы мерка
            # появилась», и он осмыслен ровно там, где мерки НЕТ. У критерия с
            # пробой, ответившей `НЕ ИЗМЕРЕНО`, причина уже названа своей строкой,
            # и приписать ему «цену привязки» значило бы ответить не на тот вопрос.
            rows.append({"criterion": name, "probe": None, "verdict": UNMEASURED,
                         "priceable": True,
                         "detail": "машинной пробы, объявившей себя мерой этого "
                                   "критерия, в реестре НЕТ — вердикт сегодня взять "
                                   "неоткуда",
                         "tree_inputs_reached": None})
            continue
        if len(probes) > 1:
            rows.append({"criterion": name, "probe": None, "verdict": UNMEASURED,
                         "detail": f"критерий объявлен мерой сразу у {len(probes)} проб "
                                   f"({', '.join(probes)}) — выбрать из них молча "
                                   f"значило бы спрятать столкновение объявлений",
                         "tree_inputs_reached": None})
            continue
        accepted = probe_tree_inputs(probes[0])
        if measure_tree or data_dir:
            # ОДНА копия правила: что предложено, то и напечатано дошедшим.
            # Прежде предложение и отчёт о нём считались ДВУМЯ выражениями, и
            # второе знало ровно два имени входа («`repo_root` — дерево, иначе —
            # данные»). Третий вход реестра (`tracker_dir`, заказ G92 п. 1) эта
            # ветка объявила бы дошедшим, не передав его: `data_dir or
            # measure_tree` истинно всегда, когда мы здесь. Поле `reached`
            # существует ровно затем, чтобы НЕ врать о достижимости, — значит
            # выводиться оно обязано из переданного, а не из второй копии мерки
            # (ADR-220: две копии одной мерки расходятся молча).
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
                     "detail": detail, "tree_inputs_reached": reached,
                     "measure": _authorship_row(authorship_report,
                                                authorship_problem, probes[0])})

    counts = {SATISFIED: 0, NOT_SATISFIED: 0, UNMEASURED: 0}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1

    # Цена меряется О ТОМ ЖЕ дереве, о котором выносится вердикт: сводка про одно
    # дерево с ценой про другое была бы двумя ответами под одним заголовком.
    price_tree = measure_tree or repo_root
    price_data = data_dir or os.path.join(price_tree, "data")
    price_problem = None
    price_report = None
    unpriced = [r["criterion"] for r in rows if r.get("priceable")]
    try:
        price_report = price_meter.measure(unpriced, repo_root=price_tree,
                                           data_dir=price_data,
                                           population=names, now=now)
    except price_meter.Unmeasured as exc:
        # Непрочитанная конституция гасит ЦЕНУ, а не сводку: вердикты выше уже
        # сняты и остаются верны. Но молчать нельзя — «цены нет» обязано быть
        # видно строкой, иначе отсутствующий столбец читается как «цены ноль».
        price_problem = str(exc)
    else:
        by_name = {r["criterion"]: r for r in price_report["rows"]}
        for row in rows:
            if row.get("priceable"):
                row["price"] = by_name.get(row["criterion"])

    # Адресат меряется ПО ОЧЕРЕДИ, а не по дереву под рукой: `nimbalyst-local/`
    # в прод-дерево не синкается (ADR-152), и карточка, которую видит владелец,
    # живёт на ref. Дерево читается второй осью и даёт свою находку (`TREE_ONLY`).
    addressee_problem = None
    addressee = None
    try:
        addressee = addressee_meter.measure(
            names, tracker_dir=os.path.join(repo_root, TRACKER_REL), ref=ref)
    except addressee_meter.Unmeasured as exc:
        # Непрочитанная очередь гасит СТОЛБЕЦ, а не сводку — тот же порядок, что
        # у цены выше: вердикты уже сняты и остаются верны, но «адресата нет»
        # обязано быть отличимо от «очередь не прочитана».
        addressee_problem = str(exc)
    else:
        by_name = {r["criterion"]: r for r in addressee["rows"]}
        for row in rows:
            row["addressee"] = by_name.get(row["criterion"])

    # ОТВЕТ заказа G95 п. 3: отказ без НАЗВАННОГО открытого вопроса владельцу
    # читается как долг агента. `None` здесь значит «адресата не мерили вовсе»,
    # и пустой список значит «мерили, таких нет» — два разных исхода (инв. #17).
    unaddressed = None
    if addressee is not None:
        unaddressed = [r["criterion"] for r in rows
                       if r["verdict"] == NOT_SATISFIED
                       and (r.get("addressee") or {}).get("kind")
                       != addressee_meter.OWNER_OPEN]

    split = bool(measure_tree and data_dir
                 and os.path.abspath(data_dir) != os.path.abspath(
                     os.path.join(measure_tree, "data")))
    return {"population": len(names), "rows": rows, "counts": counts,
            "measure_tree": measure_tree, "data_dir": data_dir,
            "split_tree": split,
            "addressee_counts": (addressee or {}).get("counts"),
            "addressee_ref": (addressee or {}).get("ref"),
            "addressee_ref_sha": (addressee or {}).get("ref_sha"),
            "addressee_cards_on_ref": (addressee or {}).get(
                "cards_declaring_on_ref"),
            "addressee_cards_in_tree": (addressee or {}).get(
                "cards_declaring_in_tree"),
            "addressee_orphan": (addressee or {}).get("orphan_declarations"),
            "addressee_problems": (addressee or {}).get("problems"),
            "addressee_problem": addressee_problem,
            "unaddressed_not_satisfied": unaddressed,
            "price_counts": (price_report or {}).get("counts"),
            "price_tree": price_tree, "price_data_dir": price_data,
            "price_problem": price_problem,
            "orphan_bindings": (price_report or {}).get("orphan_bindings"),
            "unparsed_bindings": (price_report or {}).get("unparsed_mentions"),
            "authorship": authorship_report, "authorship_problem": authorship_problem,
            "orphan_declarations": orphan, "sources": population["sources"],
            "comparison": population["comparison"],
            "population_problems": population["problems"]}


def _authorship_row(report: dict | None, problem: str | None,
                    probe_name: str) -> dict:
    """Чья мера произвела вердикт этой строки — для читателя сводки (G96 п. 3).

    До этого поля строка ``❌ НЕ ВЫПОЛНЕН  Economics  [economics_…]`` несла ДВА
    разных утверждения под одним видом: «перепись объявила находку» (порог чужой,
    спорить надо с прибором) и «проба сама сравнила число со своим порогом»
    (спорить надо с пробой). Читатель, не знающий рода, шёл не к тому адресату.

    `None`-отчёт не подменяется «своей мерой»: род становится `unmeasured` с
    названной причиной, потому что «мерку назвать нечем» и «мерит сама проба» —
    разные вещи (инв. #17).
    """
    if report is None:
        return {"kind": authorship.KIND_UNMEASURED, "instruments": [],
                "reason": problem or "род вердикта не измерен, причина не названа"}
    row = authorship.authorship_of(probe_name, report=report)
    if row is None:
        return {"kind": authorship.KIND_UNMEASURED, "instruments": [],
                "reason": (f"пробы {probe_name!r} нет в разборе реестра — род её "
                           f"вердикта НЕ ИЗМЕРЕН")}
    return {"kind": row["kind"], "instruments": row["instruments"],
            "reason": row.get("reason")}


_MARK = {SATISFIED: "✅ ВЫПОЛНЕН", NOT_SATISFIED: "❌ НЕ ВЫПОЛНЕН",
         UNMEASURED: "⚠️  НЕ ИЗМЕРЕНО"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--repo-root", default=os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))),
        help="дерево, в котором искать карточку приказа (умолчание — своё)")
    ap.add_argument("--ref", default=ORIGIN_REF, help="ветка второй копии карточки")
    ap.add_argument("--data-dir", default=None,
                    help="каталог артефактов, ОТДЕЛЬНО от --measure-tree. Нужен, "
                         "только чтобы предъявить разрыв «поверхности в одном "
                         "дереве, артефакты в другом» командой; сводка при этом "
                         "относится НИ К ОДНОМУ существующему дереву, и прибор "
                         "говорит это вслух")
    ap.add_argument("--measure-tree", default=None,
                    help="дерево, О КОТОРОМ выносится вердикт (умолчание — дерево "
                         "прибора). Доходит до пробы теми входами, которые она "
                         "объявила; что дошло, печатается у каждой строки")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
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
            print("сводки §49 нет вовсе — про критерии приказа НЕ СКАЗАНО НИЧЕГО")
        return 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        counts = report["counts"]
        print(f"§49 приказа «Portfolio CIO» — сводный замер "
              f"(население {report['population']}, прочитано из "
              f"{', '.join(report['sources'])})")
        print(f"  вердикт выносится о дереве: "
              f"{report['measure_tree'] or 'дерево прибора (' + args.repo_root + ')'}")
        if report["split_tree"]:
            print(f"  ⚠️  СБОРНЫЙ ЗАМЕР: поверхности из {report['measure_tree']}, "
                  f"артефакты из {report['data_dir']} — такого дерева НЕ "
                  f"СУЩЕСТВУЕТ, и сводка ниже не вердикт ни об одном из них")
        print(f"  {report['comparison']}")
        for problem in report["population_problems"]:
            print(f"  ⚠️  {problem}")
        print()
        for row in report["rows"]:
            mark = _MARK.get(row["verdict"], row["verdict"])
            probe = row["probe"] or "мерки нет"
            reach = row.get("tree_inputs_reached")
            tag = ("" if reach is None else
                   "  · дерево замера дошло входами: " + ", ".join(reach) if reach else
                   "  · дерево замера НЕ дошло: проба читает СВОЁ дерево")
            print(f"  {mark}  {row['criterion']}  [{probe}]{tag}")
            print(f"      {row['detail']}")
            whose = row.get("measure")
            if whose:
                over = ("" if not whose["instruments"] else
                        " ← " + ", ".join(whose["instruments"]))
                print(f"      МЕРА · "
                      f"{authorship.KIND_RU.get(whose['kind'], whose['kind'])}"
                      f"{over}")
                if whose["kind"] == authorship.KIND_SELF_JUDGED \
                        and whose["instruments"]:
                    print("      ⚠️  порог ЗДЕСЬ свой, хотя числа взяты у прибора — "
                          "спорить об этой строке надо с пробой, не с прибором")
                if whose.get("reason"):
                    print(f"      ⚠️  {whose['reason']}")
            cost = row.get("price")
            if cost:
                print(f"      ЦЕНА · {cost['price']}: "
                      f"{price_meter.PRICE_RU.get(cost['price'], '?')} — "
                      f"{cost['detail']}")
            who = row.get("addressee")
            if who:
                cards = ", ".join(f"{c['card']} [{c['status']}]"
                                  for c in who["cards"])
                print(f"      АДРЕСАТ · {who['kind']}: {who['detail']}"
                      + (f" ({cards})" if who["cards"] else ""))
                for extra in who.get("tree_only_extra") or []:
                    print(f"      ⚠️  объявление {extra} есть только в рабочем "
                          f"дереве — владельцу оно НЕ НАЗВАНО")
                for unk in who.get("unknown_status") or []:
                    print(f"      ⚠️  карточка {unk['card']} несёт статус "
                          f"{unk['status']!r} вне объявленной словарности — "
                          f"открыт ли вопрос, НЕ ИЗМЕРЕНО")
        print()
        print(f"ИТОГ: ВЫПОЛНЕНО {counts[SATISFIED]} · НЕ ВЫПОЛНЕНО "
              f"{counts[NOT_SATISFIED]} · НЕ ИЗМЕРЕНО {counts[UNMEASURED]} "
              f"из {report['population']}")
        if report["addressee_problem"]:
            print(f"  ⚠️  АДРЕСАТ НЕ НАЗВАН НИ У ОДНОГО критерия: "
                  f"{report['addressee_problem']}")
        elif report["addressee_counts"] is not None:
            print(f"  адресат мерен по очереди `{report['addressee_ref']}` "
                  f"{(report['addressee_ref_sha'] or '?')[:9]} (объявивших "
                  f"карточек: на ref {report['addressee_cards_on_ref']}, в "
                  f"дереве {report['addressee_cards_in_tree']}): "
                  + " · ".join(f"{k} {v}" for k, v in
                               sorted(report["addressee_counts"].items())))
            unaddressed = report["unaddressed_not_satisfied"]
            if unaddressed:
                print(f"  ❗ОТВЕТ G95 п. 3: из {report['counts'][NOT_SATISFIED]}"
                      f" отказ(ов) адресата владельца НЕ НАЗВАНО у "
                      f"{len(unaddressed)} — они читаются как долг агента, хотя "
                      f"починка может лежать за предметом №1 границы ADR-285: "
                      + ", ".join(unaddressed))
            elif report["counts"][NOT_SATISFIED]:
                print(f"  ✅ у каждого из {report['counts'][NOT_SATISFIED]} "
                      f"отказ(ов) адресат назван открытой карточкой владельца")
        for name, cards in sorted((report["addressee_orphan"] or {}).items()):
            print(f"  ⚠️  объявление адресата МИМО населения: "
                  f"{', '.join(cards)} объявляет себя адресатом критерия "
                  f"{name!r}, которого в §49 нет")
        for problem in report["addressee_problems"] or []:
            print(f"  ⚠️  очередь: {problem}")
        if report["price_problem"]:
            print(f"  ⚠️  ЦЕНА НЕ НАЗВАНА НИ У ОДНОГО критерия: "
                  f"{report['price_problem']}")
        elif report["price_counts"]:
            print(f"  цена мерена о дереве {report['price_tree']} "
                  f"(артефакты: {report['price_data_dir']}): "
                  + " · ".join(f"{k} {v}" for k, v in
                               sorted(report["price_counts"].items())))
        for name, paths in sorted((report["orphan_bindings"] or {}).items()):
            print(f"  ⚠️  привязка МИМО населения: {', '.join(paths)} объявлен "
                  f"мерой критерия {name!r}, которого в §49 нет")
        for miss in (report["unparsed_bindings"] or []):
            print(f"  ⚠️  §49 упомянут НЕРАЗОБРАННОЙ формой в {miss['path']}: "
                  f"{miss['snippet']!r} — привязка НЕ ИЗМЕРЕНА")
        if report["orphan_declarations"]:
            for crit, probes in sorted(report["orphan_declarations"].items()):
                print(f"  ⚠️  объявление МИМО населения: {', '.join(probes)} "
                      f"объявляет критерий {crit!r}, которого в §49 нет")
        print("ADVISORY: прибор только ЧИТАЕТ — risk-логика, стоп-кран, аллокатор, "
              "живой трек и landing/** не тронуты")

    if report["split_tree"]:
        # Сборный замер зелёным быть не может по построению: у него нет дерева,
        # о котором он говорит. Разрешить ему 0 значило бы выдать «всё выполнено»
        # за наблюдение о системе, которой нет.
        return 1
    return 0 if report["counts"][SATISFIED] == report["population"] else 1


if __name__ == "__main__":
    sys.exit(main())
