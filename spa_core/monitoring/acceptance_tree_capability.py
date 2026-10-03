#!/usr/bin/env python3
"""Какое ДЕРЕВО способно ответить на §49 приказа «Portfolio CIO» — замер по исходу.

Заказ **G93 п. 2** (ADR-505) дословно:

    «Дерево, способное ответить на §49, не существует — это предмет доставки, а не
     прибора. Поверхности владельца и живые артефакты не сходятся ни в одном дереве
     (ADR-152). Спросить надо в порядке: кто СЕГОДНЯ обязан быть деревом приёмки, и
     почему им не является ни прод, ни worktree.»

Заказ ставит вопрос утверждением, и утверждение надо было ИЗМЕРИТЬ, а не принять.
Прибор мерит ровно его и ничего больше.

## Чем этот вопрос отличается от соседнего

Сводный замер (`scripts/cio_acceptance_rollup.py`, ADR-505) отвечает «ВЫПОЛНЕН ли
критерий». Здесь вопрос другой: **способно ли дерево ВООБЩЕ вынести вердикт** — и
«выполнен», и «не выполнен» суть ОДИН исход этого вопроса (дерево ответило), а
«не измерено» — другой (дерево слепо). Смешать их значило бы спросить про
исполнение приказа вместо места его приёмки.

## Почему мера обязана быть ДИФФЕРЕНЦИАЛЬНОЙ

У одного дерева «не измерено» неотличимо от «этого наблюдения нет на свете»:
слепота дерева и отсутствие наблюдения дают ОДНО слово. Различает их только
второе дерево — если там тот же критерий отвечает, слепота есть свойство ДЕРЕВА;
если молчит и там, дерево не при чём. Поэтому деревьев обязано быть **не меньше
двух**, и при одном прибор ОТКАЗЫВАЕТ с названной причиной, а не печатает вердикт
(тот же метод, которым мерились класс pid в `.claude/rules/deployment.md` и класс
git-окружения в ADR-479).

## Пять исходов у критерия, и они не сводятся друг к другу (инв. #17)

| исход | что это значит | чем лечится |
|---|---|---|
| `tree_independent` | ответили ВСЕ измеренные деревья | ничем: место приёмки на него не влияет |
| `tree_bound` | одни ответили, другие слепы | взять дерево, которое отвечает (оно НАЗВАНО) |
| `blind_everywhere_same_reason` | слепы все и причина ОДНА | наблюдения нет в МИРЕ, а не в дереве |
| `blind_everywhere_reasons_differ` | слепы все, причины РАЗНЫЕ | «перейти в другое дерево» не закрывает |
| `no_instrument` | мерки нет ни в одном дереве | не вопрос о дереве вовсе (заказ G93 п. 1) |

**`blind_everywhere_reasons_differ` НЕ означает «сборное дерево ответило бы».**
Разные причины — это разные причины, и какая из них есть свойство дерева, а какая
свойство мира, прибор сказать не может. Утверждать обратное значило бы продать
догадку за замер; именно поэтому класс назван по НАБЛЮДЕНИЮ («причины разные»), а
не по гипотезе («нужно сборное дерево»).

Два положения дел дают `unmeasured` и названы по отдельности, а не слиты: реестр
проб РАЗОШЁЛСЯ между деревьями (деревья исполняют разный код — находка о
доставке) и критерий объявлен мерой сразу у НЕСКОЛЬКИХ проб (мерок больше одной,
а не ноль). Второе важно именно тем, что сводка отвечает о нём безымянной пробой
— так же, как о критерии БЕЗ мерки, — и прочесть одно как другое значило бы
напечатать «мерки нет» там, где мерок две.

## Отсутствующее дерево — НЕ слепое дерево

Дерева нет на диске ⇒ `tree_absent`, оно выбывает из дифференциала и называется
вслух. Считать его слепым значило бы объявить `tree_bound` КАЖДЫЙ критерий, у
которого не нашёлся каталог, — fail-OPEN наизнанку: прибор печатал бы находку
тем громче, чем хуже его собственная конфигурация.

## Сравнение причин нормализует путь дерева, и это НЕОБХОДИМО

Причина отказа пробы почти всегда несёт абсолютный путь («нет файла
`<дерево>/data/…`»), а пути деревьев различны ПО ПОСТРОЕНИЮ. Сравнить причины как
есть значило бы объявить их разными всегда, то есть получить
`blind_everywhere_reasons_differ` даром — зелёный по построению, только с обратным
знаком. Поэтому перед сравнением путь каждого дерева (и его `realpath`) заменяется
на `<ДЕРЕВО>`. Правило названо здесь и проверяется в обе стороны.

## Чего прибор НЕ докладывает

* **Верность самой пробы.** «Дерево ответило» не значит «ответило правильно»;
  правду мерки держит её собственный контроль в обе стороны
  (`.claude/rules/acceptance.md`, п. 3).
* **Какая из разных причин есть свойство дерева.** См. выше — это решение, а не
  замер.
* **Полноту перечня деревьев.** Население деревьев ОБЪЯВЛЕНО (CLI / аргумент), а
  не найдено обходом диска: угаданное дерево отвечало бы на вопрос, которого
  читатель не задавал.

ADVISORY: прибор только ЧИТАЕТ. Ни строки risk-логики, RiskPolicy, стоп-крана,
аллокатора, живого трека или `landing/**`.

## Коды возврата

* **0** — замер состоялся и ни один критерий не `tree_bound` / не слеп повсюду.
* **1** — замер состоялся и есть находки (строки печатаются числом).
* **2** — замера НЕТ ВОВСЕ: деревьев, ответивших хоть что-то, меньше двух, либо
  население §49 не прочитано. Про место приёмки при этом НЕ СКАЗАНО НИЧЕГО.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SCRIPTS = _REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from spa_core.monitoring.card_acceptance import (  # noqa: E402
    NOT_SATISFIED,
    SATISFIED,
)
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "acceptance_tree_capability.json"

#: Такт замера ступени моста. Прогон стои́т минут (пробы настоящие, деревьев
#: несколько), а предмет — КОНФИГУРАЦИЯ деревьев, которая меняется не ежечасно.
MEASUREMENT_TACT_DAYS = 7

#: Зеркало источников на Маке (ADR-152). Второе НАСТОЯЩЕЕ дерево, а не выдуманное:
#: протокол сессии прямо велит читать §1 из него, поэтому именно оно и есть тот
#: «не прод», про который спрашивает заказ.
MIRROR_DEFAULT = str(Path.home() / "Documents" / "SPA_mirror")

#: Исходы у ОДНОГО дерева.
TREE_ANSWERED = "answered"
TREE_BLIND = "blind"
TREE_NO_INSTRUMENT = "no_instrument"
#: Критерий объявлен мерой сразу у НЕСКОЛЬКИХ проб. Сводка отвечает про него
#: безымянной пробой (`probe: None`) — ровно как про критерий, у которого мерки
#: НЕТ, — но положения дел противоположны: там мер ноль, здесь их больше одной.
#: Слить их в одно слово значило бы напечатать «мерки нет» о критерии, у которого
#: мерок две (инв. #17). Различает их объявленное сводкой поле `priceable`: оно
#: существует ровно затем, чтобы отобрать строки, у которых мерки НЕТ.
TREE_PROBE_COLLISION = "probe_collision"
TREE_ABSENT = "tree_absent"

#: Исходы у критерия ПОСЛЕ сведения деревьев.
TREE_INDEPENDENT = "tree_independent"
TREE_BOUND = "tree_bound"
BLIND_SAME_REASON = "blind_everywhere_same_reason"
BLIND_REASONS_DIFFER = "blind_everywhere_reasons_differ"
NO_INSTRUMENT = "no_instrument"
VERDICT_UNMEASURED = "unmeasured"

VERDICTS = (TREE_INDEPENDENT, TREE_BOUND, BLIND_SAME_REASON,
            BLIND_REASONS_DIFFER, NO_INSTRUMENT, VERDICT_UNMEASURED)

#: Находка = критерий, у которого МЕСТО приёмки или его отсутствие решает дело.
#: `no_instrument` находкой здесь НЕ является намеренно: его цену уже назвал
#: заказ G93 п. 1, и повторять её под другим заголовком значило бы считать одну
#: дыру дважды.
FINDING_VERDICTS = (TREE_BOUND, BLIND_SAME_REASON, BLIND_REASONS_DIFFER)

VERDICT_RU = {
    TREE_INDEPENDENT: "ответили все измеренные деревья — место приёмки не решает",
    TREE_BOUND: "отвечает одно дерево, другое слепо — место приёмки РЕШАЕТ",
    BLIND_SAME_REASON: "слепы все деревья, причина ОДНА — наблюдения нет в мире",
    BLIND_REASONS_DIFFER: "слепы все деревья, причины РАЗНЫЕ — переход не лечит",
    NO_INSTRUMENT: "мерки нет ни в одном дереве — вопрос не о дереве",
    VERDICT_UNMEASURED: "дифференциал не состоялся",
}


class Unmeasured(Exception):
    """Замера нет вовсе. Несёт причину, которую обязан напечатать вызывающий."""


def normalise_reason(reason: str, trees: Sequence[str]) -> str:
    """Убрать из причины отказа путь дерева — иначе причины различны ПО ПОСТРОЕНИЮ.

    Заменяются и объявленный путь, и его `realpath`: прод-дерево и зеркало на Маке
    бывают доступны под двумя именами (`/tmp` ↔ `/private/tmp`), и сравнение,
    знающее лишь одно из них, молча объявило бы причины разными.

    Длинные пути заменяются ПЕРВЫМИ: подставь сначала короткий, и вложенное дерево
    (`/a/b` внутри `/a`) потеряло бы остаток имени, превратив разные причины в
    одинаковые. Направление ошибки здесь важнее аккуратности: это fail-OPEN, он
    гасил бы находку.
    """
    out = str(reason)
    names: set[str] = set()
    for tree in trees:
        if not tree:
            continue
        names.add(str(tree))
        try:
            names.add(str(Path(tree).resolve()))
        except OSError:
            pass
    for name in sorted(names, key=len, reverse=True):
        out = out.replace(name, "<ДЕРЕВО>")
    return out


def _tree_rows(tree: str, *, ref: str, card_rel: Optional[str],
               probe_runner: Optional[Callable], rollup) -> dict:
    """Один замер сводки О ДЕРЕВЕ `tree`. Отказ дерева — исход, а не исключение.

    Дерево подаётся сводке и как `repo_root` (откуда читать население §49), и как
    `measure_tree` (о чём выносить вердикт) — НАМЕРЕННО обоими. Прочитать
    население из одного дерева, а мерить другое значило бы сделать проверку
    расхождения населений зелёной ПО ПОСТРОЕНИЮ: население было бы одно и то же
    по происхождению, и расхождение стало бы недостижимо. А оно достижимо:
    карточка приказа лежит в `nimbalyst-local/`, который в прод-дерево не
    синхронизируется (ADR-152), и копии расходятся штатно.
    """
    if not os.path.isdir(tree):
        return {"tree": tree, "state": TREE_ABSENT,
                "reason": f"каталога {tree} на диске нет — дерево выбывает из "
                          f"дифференциала, слепым оно НЕ объявляется"}
    kw: dict = {"measure_tree": tree, "ref": ref}
    if card_rel is not None:
        kw["card_rel"] = card_rel
    if probe_runner is not None:
        kw["probe_runner"] = probe_runner
    try:
        report = rollup.measure(tree, **kw)
    except rollup.Unmeasured as exc:
        return {"tree": tree, "state": VERDICT_UNMEASURED,
                "reason": f"сводка §49 о дереве {tree} не снята: {exc}"}
    rows = {}
    for row in report.get("rows") or ():
        verdict = row.get("verdict")
        if row.get("probe") is None:
            # Безымянная проба не есть ответ НИ ПРИ КАКОМ вердикте. Прежняя
            # редакция требовала здесь ещё и `verdict == UNMEASURED`, и это был
            # fail-OPEN: строка со вердиктом `satisfied` и БЕЗ названной мерки
            # проваливалась ниже и считалась «дерево ответило». Утверждение без
            # мерки — не ответ, а претензия; найдено мутацией M26b, не чтением.
            #
            # `priceable` — объявление САМОЙ сводки: «у этого критерия мерки нет»
            # (на нём держится её замер цены, G93 п. 1). Его отсутствие при
            # безымянной пробе означает другое положение дел — столкновение
            # объявлений, — и прочесть его как «мерки нет» значило бы напечатать
            # ноль мер о критерии, у которого их больше одной.
            state = (TREE_NO_INSTRUMENT if row.get("priceable")
                     else TREE_PROBE_COLLISION)
        elif verdict in (SATISFIED, NOT_SATISFIED):
            state = TREE_ANSWERED
        else:
            state = TREE_BLIND
        rows[row["criterion"]] = {"state": state, "probe": row.get("probe"),
                                  "probe_verdict": verdict,
                                  "detail": row.get("detail") or ""}
    return {"tree": tree, "state": "measured", "rows": rows,
            "population": report.get("population"),
            "criteria": [r["criterion"] for r in report.get("rows") or ()]}


def classify(criterion: str, per_tree: dict, trees: Sequence[str]) -> dict:
    """Свести исходы ОДНОГО критерия по деревьям в один вердикт.

    `per_tree` — дерево → запись из :func:`_tree_rows`. Деревья, выбывшие из
    дифференциала (`tree_absent`, отказ сводки), сюда не попадают: их исключает
    вызывающий, и исключение НАЗЫВАЕТСЯ им же.
    """
    answered = sorted(t for t, r in per_tree.items() if r["state"] == TREE_ANSWERED)
    blind = sorted(t for t, r in per_tree.items() if r["state"] == TREE_BLIND)
    absent_probe = sorted(t for t, r in per_tree.items()
                          if r["state"] == TREE_NO_INSTRUMENT)
    collided = sorted(t for t, r in per_tree.items()
                      if r["state"] == TREE_PROBE_COLLISION)

    if collided:
        # Столкновение объявлений сильнее любого из прочих исходов: пока не
        # решено, КАКАЯ проба есть мера критерия, вердикт о дереве относится к
        # неизвестно чему. Выбрать пробу молча значило бы спрятать столкновение.
        return {"criterion": criterion, "verdict": VERDICT_UNMEASURED,
                "answered_in": answered, "blind_in": blind,
                "detail": f"критерий объявлен мерой сразу у НЕСКОЛЬКИХ проб "
                          f"(деревья: {', '.join(collided)}) — мерок больше одной, "
                          f"а не ноль; пока не решено, какая из них мера, вердикт "
                          f"о дереве относится к неизвестно чему"}
    if absent_probe and not answered and not blind:
        return {"criterion": criterion, "verdict": NO_INSTRUMENT,
                "answered_in": [], "blind_in": [],
                "detail": "машинной пробы, объявившей себя мерой этого критерия, в "
                          "реестре НЕТ — ни одно дерево ответить не может, и это "
                          "вопрос о МЕРКЕ, а не о дереве (заказ G93 п. 1)"}
    if absent_probe and (answered or blind):
        # Реестр проб у всех деревьев ОДИН (он в коде, не в данных), поэтому
        # «мерки нет здесь, а там есть» означает, что деревья исполняют РАЗНЫЙ
        # код. Это находка о доставке, и выдать её за вердикт о критерии нельзя.
        return {"criterion": criterion, "verdict": VERDICT_UNMEASURED,
                "answered_in": answered, "blind_in": blind,
                "detail": f"реестр проб РАЗОШЁЛСЯ между деревьями: мерки нет в "
                          f"{', '.join(absent_probe)}, а в "
                          f"{', '.join(answered + blind)} она есть — деревья "
                          f"исполняют разный код, и вердикт о критерии из этого "
                          f"не выводится"}
    if answered and not blind:
        return {"criterion": criterion, "verdict": TREE_INDEPENDENT,
                "answered_in": answered, "blind_in": [],
                "detail": f"ответили все измеренные деревья ({', '.join(answered)}) — "
                          f"место приёмки этого критерия не решает"}
    if answered and blind:
        return {"criterion": criterion, "verdict": TREE_BOUND,
                "answered_in": answered, "blind_in": blind,
                "detail": f"отвечает {', '.join(answered)}; слепо "
                          f"{', '.join(blind)} — дерево приёмки этого критерия "
                          f"НАЗВАНО замером, а не выбрано"}

    reasons = {normalise_reason(per_tree[t]["detail"], trees) for t in blind}
    if len(reasons) == 1:
        return {"criterion": criterion, "verdict": BLIND_SAME_REASON,
                "answered_in": [], "blind_in": blind,
                "detail": f"слепы все измеренные деревья ({', '.join(blind)}) и "
                          f"причина ОДНА (после снятия пути дерева) — наблюдения "
                          f"нет в МИРЕ, сменой дерева это не чинится: "
                          f"{sorted(reasons)[0][:200]}"}
    return {"criterion": criterion, "verdict": BLIND_REASONS_DIFFER,
            "answered_in": [], "blind_in": blind,
            "detail": "слепы все измеренные деревья, и причины РАЗНЫЕ: "
                      + " · ".join(f"{t}: {normalise_reason(per_tree[t]['detail'], trees)[:140]}"
                                   for t in blind)
                      + " — «перейти в другое дерево» этого не закрывает; какая из "
                        "причин есть свойство дерева, а какая свойство мира, прибор "
                        "НЕ ДОКЛАДЫВАЕТ"}


def measure(repo_root: str | Path = _REPO_ROOT, *, trees: Optional[Sequence[str]] = None,
            ref: str = "origin/main", card_rel: Optional[str] = None,
            probe_runner: Optional[Callable] = None, rollup=None, now=None) -> dict:
    """Свести способность деревьев отвечать на §49. Бросает :class:`Unmeasured`.

    `repo_root` здесь — НЕ место чтения населения (его читает каждое дерево у
    себя, см. :func:`_tree_rows`), а лишь первый кандидат по умолчанию: своё
    дерево против зеркала источников.

    `rollup` подменяем намеренно: мерка разрешается В МОМЕНТ ЗОВА, а не умолчанием
    в сигнатуре — умолчание связывается при ОПРЕДЕЛЕНИИ функции, и контроль,
    думающий, что подменил сводку, мерил бы настоящую (зелёный по построению,
    урок ADR-505).

    Правило «что дошло до пробы» НЕ копируется: сводка `cio_acceptance_rollup`
    уже его держит, и вторая копия разошлась бы с ней молча (ADR-220).
    """
    if rollup is None:
        import cio_acceptance_rollup as rollup  # noqa: PLC0415
    repo_root = str(repo_root)
    declared = list(trees) if trees is not None else [repo_root, MIRROR_DEFAULT]
    # Одно и то же дерево, названное дважды, дифференциалом не является: оно
    # согласится с собой по построению и покрасило бы всё в `tree_independent`.
    seen: list[str] = []
    for tree in declared:
        key = os.path.abspath(tree)
        if key not in [os.path.abspath(t) for t in seen]:
            seen.append(tree)
    declared = seen

    if len(declared) < 2:
        raise Unmeasured(
            f"объявлено деревьев: {len(declared)} ({', '.join(declared) or '—'}). "
            f"Дифференциал требует ДВУХ: у одного дерева «слепо здесь» неотличимо "
            f"от «наблюдения нет на свете», и обе половины дают одно слово")

    measured: dict[str, dict] = {}
    excluded: list[dict] = []
    for tree in declared:
        row = _tree_rows(tree, ref=ref, card_rel=card_rel,
                         probe_runner=probe_runner, rollup=rollup)
        if row["state"] == "measured":
            measured[tree] = row
        else:
            excluded.append(row)

    if len(measured) < 2:
        raise Unmeasured(
            "сводку §49 дали меньше двух деревьев, дифференциал НЕ СОСТОЯЛСЯ: "
            + " · ".join(f"{r['tree']} — {r['reason']}" for r in excluded)
            + (f" · измерено: {', '.join(measured)}" if measured else ""))

    populations = {tree: tuple(row["criteria"]) for tree, row in measured.items()}
    first = next(iter(populations.values()))
    for tree, pop in populations.items():
        if pop != first:
            raise Unmeasured(
                f"деревья дают РАЗНОЕ население §49: у {next(iter(populations))} — "
                f"{len(first)} критери(й/ев), у {tree} — {len(pop)}; свести "
                f"способности разных населений нельзя, это два разных приказа")

    rows = []
    for criterion in first:
        per_tree = {t: measured[t]["rows"][criterion] for t in measured
                    if criterion in measured[t]["rows"]}
        row = classify(criterion, per_tree, list(measured))
        row["per_tree"] = {t: {"state": v["state"], "probe": v["probe"],
                               "probe_verdict": v["probe_verdict"],
                               "detail": v["detail"]}
                           for t, v in per_tree.items()}
        rows.append(row)

    counts = {v: 0 for v in VERDICTS}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1

    answered_by_tree = {t: sum(1 for r in rows
                               if t in (r.get("answered_in") or ()))
                        for t in measured}
    best = max(answered_by_tree.values()) if answered_by_tree else 0
    winners = sorted(t for t, n in answered_by_tree.items() if n == best)
    if best == 0:
        acceptance_tree = None
        acceptance_detail = ("ни одно измеренное дерево не ответило НИ ПО ОДНОМУ "
                             "критерию — дерева приёмки сегодня нет вовсе")
    elif len(winners) > 1:
        acceptance_tree = None
        acceptance_detail = (f"деревья отвечают РАВНО по {best} критери(ю/ям) "
                             f"({', '.join(winners)}) — выбрать из них молча значило "
                             f"бы решить за читателя; старшинство НЕ ИЗМЕРЕНО")
    else:
        acceptance_tree = winners[0]
        acceptance_detail = (f"дерево приёмки СЕГОДНЯ — {winners[0]}: оно отвечает по "
                             f"{best} критери(ю/ям) из {len(rows)}; "
                             + " · ".join(f"{t}: {n}" for t, n
                                          in sorted(answered_by_tree.items())))

    # Отметка замера ОБЯЗАТЕЛЬНА, и причин две, обе измерены на этом приборе.
    # (1) Такт решает ФАЙЛ, а файл отвечает полем `generated_at`: без него
    #     `measurement_due` честно говорит «отметка не прочитана — мерим», и
    #     объявленный такт 7 дн становится прозой, а дорогая ступень идёт каждый
    #     тик моста. (2) Сам вердикт есть ЗАМЕР С ДАТОЙ, а не состояние: два
    #     прогона 03.10 с разницей в час дали РАЗНЫЕ числа (`Costs` перешёл из
    #     «слеп повсюду» в «отвечает в проде», когда флот обновил наблюдение
    #     газа). Число без даты здесь — перепечатка, которая молча перестаёт
    #     быть правдой.
    return {"status": "OK", "generated_at": _stamp_now(now),
            "population": len(rows), "rows": rows, "counts": counts,
            "trees_measured": sorted(measured), "trees_excluded": excluded,
            "answered_by_tree": answered_by_tree,
            "acceptance_tree": acceptance_tree,
            "acceptance_detail": acceptance_detail,
            "findings": sum(counts.get(v, 0) for v in FINDING_VERDICTS)}


def _stamp_now(now=None) -> str:
    """Момент замера строкой ISO с поясом. Часы — ВХОД, а не окружение."""
    moment = now if now is not None else dt.datetime.now(dt.timezone.utc)
    return moment.isoformat()


def run(root: str | Path = _REPO_ROOT, *, data_dir: Optional[Path] = None,
        dest: Optional[Path] = None, write: bool = True, if_due: bool = True,
        trees: Optional[Sequence[str]] = None, now=None,
        tact_days: int = MEASUREMENT_TACT_DAYS, **kw) -> dict:
    """Один ТАКТ замера для ступени моста (`findings_bridge.CENSUS_STAGE`).

    **«Не мерили» и «измерено» — РАЗНЫЕ исходы** (инв. #17): внутри такта
    возвращается ``{"measured": False, "reason": …}``, а не выдуманный вердикт.
    Ноль находок в этой ветке был бы утверждением о населении, которого никто не
    смотрел.

    Гейт такта НЕ копируется — он взят у соседа (`python_reader_clock_doors`),
    который его уже меряет: две копии одной мерки расходятся молча (ADR-220).
    """
    root = Path(root)
    source = Path(data_dir) if data_dir is not None else root / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    if if_due:
        from spa_core.monitoring.python_reader_clock_doors import measurement_due
        due, why = measurement_due(target, now=now, tact_days=tact_days)
        if not due:
            return {"measured": False, "reason": why, "artifact": str(target)}
    try:
        doc = measure(root, trees=trees, now=now, **kw)
    except Unmeasured as exc:
        # Отметка стои́т и у ОТКАЗА: иначе один отказ делал бы такт нечитаемым
        # навсегда — «не смогли прочитать, когда мерили» означает «мерим», и
        # дорогая ступень пошла бы каждый тик моста до конца времён.
        doc = {"status": "UNMEASURED", "reason": str(exc),
               "generated_at": _stamp_now(now)}
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def report(doc: dict, max_rows: int = 25) -> list[str]:
    lines: list[str] = []
    if str(doc.get("status")) != "OK":
        lines.append(f"НЕ ИЗМЕРЕНО: {doc.get('reason', 'причина не названа')}")
        lines.append("  про дерево приёмки §49 НЕ СКАЗАНО НИЧЕГО — выдать это за "
                     "«подходит любое» нельзя")
        return lines
    counts = observed(doc, "counts", kind=dict) or {}
    lines.append(
        f"Дерево приёмки §49 (заказ G93 п. 2): население {doc.get('population')} "
        f"критери(й/ев), деревьев измерено "
        f"{len(doc.get('trees_measured') or ())} "
        f"({', '.join(doc.get('trees_measured') or ())})")
    lines.append("  " + " · ".join(f"{v} {counts.get(v, 0)}" for v in VERDICTS))
    lines.append(f"  ОТВЕТ: {doc.get('acceptance_detail')}")
    for row in doc.get("trees_excluded") or ():
        lines.append(f"  ⚠️  дерево ВЫБЫЛО из дифференциала: {row.get('reason')}")
    shown = 0
    for row in doc.get("rows") or ():
        if row["verdict"] not in FINDING_VERDICTS:
            continue
        if shown >= max_rows:
            break
        lines.append(f"  [{row['verdict']}] {row['criterion']} — {row['detail']}")
        shown += 1
    rest = int(doc.get("findings") or 0) - shown
    if rest > 0:
        lines.append(f"  … ещё {rest} находк(и) того же вида (полный перечень — `--json`)")
    lines.append("  НЕ ДОКЛАДЫВАЕТ: верна ли сама проба (ответ дерева не есть "
                 "правильный ответ) · какая из РАЗНЫХ причин есть свойство дерева, а "
                 "какая свойство мира · полноту перечня деревьев (он объявлен, а не "
                 "найден обходом диска)")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return lines


def format_report(doc: dict, max_rows: int = 10) -> list[str]:
    """Отрисовка для шага 0-офис. Правило отрисовки живёт У ПРОИЗВОДИТЕЛЯ — вторая
    копия у читателя разошлась бы с ним молча (ADR-220)."""
    head = ["— дерево приёмки §49 приказа «Portfolio CIO» (ADR-545) —"]
    return head + ["   " + line for line in report(doc, max_rows=max_rows)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=str(_REPO_ROOT),
                    help="дерево, в котором искать карточку приказа")
    ap.add_argument("--tree", action="append", default=None,
                    help="дерево-кандидат (можно повторять). Умолчание — своё "
                         "дерево и зеркало источников; МЕНЬШЕ ДВУХ = отказ")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-rows", type=int, default=25)
    args = ap.parse_args(argv)

    try:
        doc = measure(args.repo_root, trees=args.tree, ref=args.ref)
    except Unmeasured as exc:
        doc = {"status": "UNMEASURED", "reason": str(exc)}
    if not args.no_write:
        dest = Path(args.out) if args.out else Path(args.repo_root) / "data" / ARTIFACT
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(dest))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for line in report(doc, max_rows=args.max_rows):
            print(line)
    if str(doc.get("status")) != "OK":
        return 2
    return 1 if int(doc.get("findings") or 0) else 0


if __name__ == "__main__":
    sys.exit(main())
