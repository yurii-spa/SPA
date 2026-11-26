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

### Поправка ADR-1119 (цикл #1264): догадку заменил ЗАМЕР, и он РАЗЛИЧАЕТ

Абзац выше сохранён дословно: он верен про ДОГАДКУ и неверен про возможность
замера. «Сборное дерево ответило бы» и правда нельзя утверждать словами — но
**можно СПРОСИТЬ**, и дверь для этого уже существовала: сводка §49
(`cio_acceptance_rollup.measure`) принимает `measure_tree` и `data_dir`
РАЗДЕЛЬНО и сама печатает «СБОРНЫЙ ЗАМЕР … такого дерева НЕ СУЩЕСТВУЕТ». Прибор
этой двери не звал ни разу, поэтому `blind_everywhere_*` был КОНЦОМ вопроса там,
где он был его серединой.

Замер 2026-11-27 (цикл #1264, два настоящих дерева: прод `~/Documents/SPA_Claude`
и зеркало `~/Documents/SPA_mirror`; слепых повсюду критериев **5**):

| исход сборной пары | критерии |
|---|---|
| **ПАРА ОТВЕЧАЕТ** — 1 | `Owner visibility`: поверхности из зеркала × артефакты из прод-`data/` дают **ВЫПОЛНЕН, 12 из 12** |
| пара спрошена и слепа — 3 | `Determinism`, `Auditability`, `Shadow verification`: артефакт протух в проде и отсутствует в зеркале ⇒ причина есть свойство МИРА (`com.spa.decision_loop` выключен), а не дерева |
| **пару СПРОСИТЬ НЕЛЬЗЯ** — 1 | `No regression`: проба не объявляет входа `data_dir`, пара сводится к дереву поверхностей и о СБОРНОМ дереве не отвечает (класс ADR-1107) |

Ось **РАЗЛИЧАЕТ**, а не отвечает «ответила бы» всегда: 1 из 5. Именно поэтому
она есть замер, а не та догадка, которую абзац выше правильно запрещал. И
`Owner visibility` — критерий ПРИКАЗА ВЛАДЕЛЬЦА, который числился слепым
повсюду, будучи ОТВЕТИМЫМ.

Три исхода оси разведены и не склеиваются (инв. #17): `answered` · `blind`
(пара спрошена и тоже слепа) · `unmeasured` с НАЗВАННОЙ причиной. Четвёртый,
`not_asked`, стои́т у критерия, который слепым повсюду не оказался: «вопрос не
стои́т» обязано быть отличимо от «спросили и не нашли».

**Ответ пары НЕ делает пару деревом.** Такого дерева не существует, и вердикт о
нём не есть вердикт ни об одном из двух; поэтому исход назван
`answerable_by_a_tree_pairing`, а не `tree_bound`, и пара ПЕЧАТАЕТСЯ поимённо.

**Ось платит отдельным прогоном настоящих проб за КАЖДУЮ пару**, поэтому она
спрашивается только при непустом населении слепых и только до объявленного
потолка пар (:data:`MAX_PAIRINGS`). Потолок превышен ⇒ `unmeasured` с названной
причиной, а не молчаливое усечение перечня: ответ о паре, которой не
спрашивали, хуже отсутствия ответа. Цена ИЗМЕРЯЕТСЯ и ПЕЧАТАЕТСЯ (замер #1264:
83.7 с без оси, пара ≈ 42 с).

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
* **Какая из разных причин есть свойство дерева** — по ОТДЕЛЬНОСТИ. Ось сборной
  пары (ADR-1119) отвечает о ПАРЕ целиком: «эта пара отвечает» либо «эта пара
  тоже слепа». Разложить слепоту на вклад каждой причины она не берётся, и
  утверждать такое разложение по-прежнему значило бы продать догадку за замер.
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
import time
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
#: Ни одно ОДИНОЧНОЕ дерево не ответило, а СБОРНАЯ ПАРА (поверхности из одного ×
#: артефакты из другого) ответила. Имя намеренно не `tree_bound`: дерева с такой
#: парой НЕ СУЩЕСТВУЕТ, и выдать пару за дерево значило бы назвать местом приёмки
#: то, чего нет на диске (ADR-1119).
ANSWERABLE_BY_PAIRING = "answerable_by_a_tree_pairing"
NO_INSTRUMENT = "no_instrument"
VERDICT_UNMEASURED = "unmeasured"

VERDICTS = (TREE_INDEPENDENT, TREE_BOUND, BLIND_SAME_REASON,
            BLIND_REASONS_DIFFER, ANSWERABLE_BY_PAIRING, NO_INSTRUMENT,
            VERDICT_UNMEASURED)

#: Исходы ОСИ СБОРНОЙ ПАРЫ у одного критерия. Четыре, и они не склеиваются:
#: «вопрос не стои́т» обязано быть отличимо от «спросили и не нашли», а оба —
#: от «спросить нельзя, и вот почему» (инв. #17).
PAIRING_NOT_ASKED = "not_asked"
PAIRING_ANSWERED = "answered"
PAIRING_BLIND = "blind"
PAIRING_UNMEASURED = "unmeasured"

PAIRING_STATES = (PAIRING_NOT_ASKED, PAIRING_ANSWERED, PAIRING_BLIND,
                  PAIRING_UNMEASURED)

#: Потолок числа УПОРЯДОЧЕННЫХ пар, которые ось берётся спросить. Каждая пара —
#: отдельный прогон настоящих проб (замер #1264: ≈42 с), поэтому цена растёт как
#: N·(N−1). Потолок превышен ⇒ ось отвечает `unmeasured` с названной причиной, а
#: НЕ усекает перечень молча: ответ о паре, которой не спрашивали, хуже отсутствия
#: ответа. Шесть = полный набор пар для трёх деревьев.
MAX_PAIRINGS = 6

#: Находка = критерий, у которого МЕСТО приёмки или его отсутствие решает дело.
#: `no_instrument` находкой здесь НЕ является намеренно: его цену уже назвал
#: заказ G93 п. 1, и повторять её под другим заголовком значило бы считать одну
#: дыру дважды.
FINDING_VERDICTS = (TREE_BOUND, BLIND_SAME_REASON, BLIND_REASONS_DIFFER,
                    ANSWERABLE_BY_PAIRING)

VERDICT_RU = {
    TREE_INDEPENDENT: "ответили все измеренные деревья — место приёмки не решает",
    TREE_BOUND: "отвечает одно дерево, другое слепо — место приёмки РЕШАЕТ",
    BLIND_SAME_REASON: "слепы все деревья, причина ОДНА — наблюдения нет в мире",
    BLIND_REASONS_DIFFER: "слепы все деревья, причины РАЗНЫЕ — переход не лечит",
    ANSWERABLE_BY_PAIRING: ("одиночное дерево не ответило, а СБОРНАЯ ПАРА "
                            "ответила — критерий ОТВЕТИМ, дерева с такой парой нет"),
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


def _pairing_rows(surfaces: str, data_tree: str, *, ref: str,
                  card_rel: Optional[str], probe_runner: Optional[Callable],
                  rollup) -> dict:
    """Один СБОРНЫЙ замер: поверхности из `surfaces`, артефакты из `data_tree`/data.

    Дерева с таким составом НЕ СУЩЕСТВУЕТ — сводка §49 это и печатает сама. Здесь
    важно, что `measure_tree` и `data_dir` подаются РАЗДЕЛЬНО: подай их вместе, и
    замер выродился бы в уже снятый вердикт об одном дереве, то есть ось отвечала
    бы на вопрос, который прибор задал два раза.

    Население читается из дерева ПОВЕРХНОСТЕЙ — тем же правилом, что у
    :func:`_tree_rows`. Равенство населений деревьев проверено вызывающим ДО оси,
    поэтому выбор здесь не решает вердикта, но назван, а не оставлен неявным.
    """
    kw: dict = {"measure_tree": surfaces, "ref": ref,
                "data_dir": os.path.join(data_tree, "data")}
    if card_rel is not None:
        kw["card_rel"] = card_rel
    if probe_runner is not None:
        kw["probe_runner"] = probe_runner
    try:
        report = rollup.measure(surfaces, **kw)
    except rollup.Unmeasured as exc:
        return {"state": PAIRING_UNMEASURED,
                "reason": f"сводка §49 о сборной паре не снята: {exc}"}
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return {"state": PAIRING_UNMEASURED,
                "reason": f"сводка §49 о сборной паре упала: "
                          f"{type(exc).__name__}: {exc}"}
    rows = {}
    for row in report.get("rows") or ():
        rows[row["criterion"]] = {
            "verdict": row.get("verdict"),
            "detail": row.get("detail") or "",
            "declared": list(row.get("tree_inputs_declared") or ()),
            "reached": list(row.get("tree_inputs_reached") or ()),
        }
    return {"state": "measured", "rows": rows}


def _pairing_verdict(criterion: str, seen: Sequence[dict]) -> dict:
    """Свести ответы всех пар об ОДНОМ критерии в один исход оси.

    Старшинство: ответ пары сильнее всего (он снимает вопрос) · затем
    РАССОГЛАСОВАНИЕ (пара ответила, не получив `data_dir`, — значит она равна
    дереву поверхностей, а то дерево слепо: два замера спорят, и выдать спор за
    ответ нельзя) · затем «спрошена и слепа» · затем названная причина, почему
    спросить не вышло. Пустой перечень есть `unmeasured`, а не `blind`: ноль пар
    не является утверждением о парах.
    """
    answered = [s for s in seen if s.get("outcome") == PAIRING_ANSWERED]
    if answered:
        return {"status": PAIRING_ANSWERED, "tried": len(seen),
                "answered_by": [{"surfaces": s["surfaces"], "data_dir": s["data_dir"],
                                 "probe_verdict": s["probe_verdict"],
                                 "detail": s.get("detail", "")[:400]}
                                for s in answered],
                "pairings": [_pairing_brief(s) for s in seen]}
    contradicting = [s for s in seen if s.get("outcome") == "contradiction"]
    if contradicting:
        first = contradicting[0]
        return {"status": PAIRING_UNMEASURED, "tried": len(seen), "answered_by": [],
                "reason": (f"пара (поверхности {first['surfaces']} × артефакты "
                           f"{first['data_dir']}) вынесла вердикт "
                           f"{first['probe_verdict']}, НЕ получив входа `data_dir` "
                           f"(дошли: {', '.join(first['reached']) or '—'}) — значит "
                           f"она равна дереву поверхностей, а оно слепо: два замера "
                           f"СПОРЯТ, и спор ответом о сборном дереве не является"),
                "pairings": [_pairing_brief(s) for s in seen]}
    blind = [s for s in seen if s.get("outcome") == PAIRING_BLIND]
    if blind:
        return {"status": PAIRING_BLIND, "tried": len(seen), "answered_by": [],
                "reason": (f"спрошено пар: {len(blind)}, и каждая тоже слепа ⇒ "
                           f"причина слепоты есть свойство МИРА, а не дерева: "
                           + blind[0].get("detail", "")[:200]),
                "pairings": [_pairing_brief(s) for s in seen]}
    if not seen:
        return {"status": PAIRING_UNMEASURED, "tried": 0, "answered_by": [],
                "reason": "ни одна пара о критерии не ответила ВОВСЕ — перечень пар "
                          "пуст, и ноль пар утверждением о парах не является",
                "pairings": []}
    return {"status": PAIRING_UNMEASURED, "tried": len(seen), "answered_by": [],
            "reason": seen[0].get("reason")
                      or "причина, по которой пару спросить не вышло, НЕ НАЗВАНА",
            "pairings": [_pairing_brief(s) for s in seen]}


def _pairing_brief(seen: dict) -> dict:
    """Пара в отчёте называется ПОИМЁННО: иначе «ось спрошена» нечем проверить."""
    return {"surfaces": seen.get("surfaces"), "data_dir": seen.get("data_dir"),
            "outcome": seen.get("outcome"), "probe_verdict": seen.get("probe_verdict"),
            "reached": list(seen.get("reached") or ()),
            "declared": list(seen.get("declared") or ())}


def ask_pairings(trees: Sequence[str], blind: Sequence[str], *, ref: str,
                 card_rel: Optional[str], probe_runner: Optional[Callable],
                 rollup, clock: Optional[Callable] = None) -> tuple[dict, dict]:
    """Спросить СБОРНЫЕ пары о критериях, слепых во ВСЕХ измеренных деревьях.

    Возвращает `(критерий → исход оси, сводка оси)`. Пары УПОРЯДОЧЕННЫЕ: «поверхности
    из A, артефакты из B» и обратное — РАЗНЫЕ вопросы (замер #1264: отвечает ровно
    одна сторона из двух), и считать их одной парой значило бы потерять половину.

    Цена МЕРИТСЯ, а не оценивается: ось платит отдельным прогоном настоящих проб за
    каждую пару, и число секунд печатается рядом с вердиктом.
    """
    tick = clock or time.monotonic
    ordered = [(a, b) for a in trees for b in trees
               if os.path.abspath(a) != os.path.abspath(b)]
    meta: dict = {"pairings_declared": len(ordered), "blind_population": len(blind),
                  "cap": MAX_PAIRINGS, "seconds": 0.0, "pairings": []}
    if not blind:
        meta["reason"] = ("слепых повсюду критериев нет — вопрос о сборном дереве "
                          "не стои́т, и ось не спрашивалась")
        return {}, meta
    if not ordered:
        reason = ("упорядоченных пар из измеренных деревьев не получилось ни одной — "
                  "о сборном дереве спросить нечем")
        meta["reason"] = reason
        return ({c: {"status": PAIRING_UNMEASURED, "tried": 0, "answered_by": [],
                     "reason": reason, "pairings": []} for c in blind}, meta)
    if len(ordered) > MAX_PAIRINGS:
        reason = (f"пар {len(ordered)} при объявленном потолке {MAX_PAIRINGS}: каждая "
                  f"пара стои́т отдельного прогона настоящих проб, а усечь перечень "
                  f"молча значило бы ответить о паре, которой не спрашивали")
        meta["reason"] = reason
        return ({c: {"status": PAIRING_UNMEASURED, "tried": 0, "answered_by": [],
                     "reason": reason, "pairings": []} for c in blind}, meta)

    seen: dict[str, list[dict]] = {c: [] for c in blind}
    started = tick()
    for surfaces, data_tree in ordered:
        data_dir = os.path.join(data_tree, "data")
        taken = _pairing_rows(surfaces, data_tree, ref=ref, card_rel=card_rel,
                              probe_runner=probe_runner, rollup=rollup)
        meta["pairings"].append({"surfaces": surfaces, "data_dir": data_dir,
                                 "state": taken["state"],
                                 "reason": taken.get("reason")})
        if taken["state"] != "measured":
            for criterion in blind:
                seen[criterion].append({"surfaces": surfaces, "data_dir": data_dir,
                                        "outcome": PAIRING_UNMEASURED,
                                        "reason": taken.get("reason"),
                                        "probe_verdict": None, "reached": [],
                                        "declared": []})
            continue
        for criterion in blind:
            got = (taken["rows"] or {}).get(criterion)
            if got is None:
                seen[criterion].append({
                    "surfaces": surfaces, "data_dir": data_dir,
                    "outcome": PAIRING_UNMEASURED, "probe_verdict": None,
                    "reached": [], "declared": [],
                    "reason": (f"сводка сборной пары о критерии {criterion!r} строки "
                               f"не дала — населения пары и деревьев РАСХОДЯТСЯ, и "
                               f"молчание о критерии ответом не является")})
                continue
            reached = list(got.get("reached") or ())
            declared = list(got.get("declared") or ())
            verdict = got.get("verdict")
            assembled = "data_dir" in reached and "repo_root" in reached
            if verdict in (SATISFIED, NOT_SATISFIED):
                outcome = PAIRING_ANSWERED if assembled else "contradiction"
            elif assembled:
                outcome = PAIRING_BLIND
            elif "data_dir" not in declared:
                outcome = PAIRING_UNMEASURED
            else:
                outcome = PAIRING_UNMEASURED
            entry = {"surfaces": surfaces, "data_dir": data_dir, "outcome": outcome,
                     "probe_verdict": verdict, "reached": reached,
                     "declared": declared, "detail": got.get("detail", "")}
            if outcome == PAIRING_UNMEASURED:
                if "data_dir" not in declared:
                    entry["reason"] = (
                        f"проба критерия не объявляет входа `data_dir` (объявлено: "
                        f"{', '.join(declared) or '—'}) — сборная пара сводится к "
                        f"дереву поверхностей {surfaces} и о СБОРНОМ дереве не "
                        f"отвечает; это НЕ «пара тоже слепа»")
                else:
                    entry["reason"] = (
                        f"вход `data_dir` до пробы НЕ ДОШЁЛ (объявлено: "
                        f"{', '.join(declared) or '—'}; дошло: "
                        f"{', '.join(reached) or '—'}) — о сборном дереве замера нет")
            seen[criterion].append(entry)
    meta["seconds"] = round(tick() - started, 3)
    return ({c: _pairing_verdict(c, seen[c]) for c in blind}, meta)


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
            probe_runner: Optional[Callable] = None, rollup=None, now=None,
            pairings: bool = True, clock: Optional[Callable] = None) -> dict:
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

    # --- ось СБОРНОЙ ПАРЫ (ADR-1119): «слепы все деревья» не есть конец вопроса.
    # Спрашивается ТОЛЬКО о слепых повсюду критериях: у остальных пара ничего не
    # добавляет, а стои́т отдельного прогона настоящих проб. Ось ВЫКЛЮЧАЕМА входом,
    # и выключенная она отвечает `unmeasured` с названной причиной, а НЕ молчит:
    # молчание сделало бы «не спрашивали» неотличимым от «спросили и не нашли».
    blind_everywhere = [r["criterion"] for r in rows
                        if r["verdict"] in (BLIND_SAME_REASON, BLIND_REASONS_DIFFER)]
    if pairings:
        pair_verdicts, pair_meta = ask_pairings(
            sorted(measured), blind_everywhere, ref=ref, card_rel=card_rel,
            probe_runner=probe_runner, rollup=rollup, clock=clock)
    else:
        pair_meta = {"pairings_declared": 0, "blind_population": len(blind_everywhere),
                     "cap": MAX_PAIRINGS, "seconds": 0.0, "pairings": [],
                     "reason": "ось сборной пары ВЫКЛЮЧЕНА входом `pairings=False` — "
                               "о сборном дереве не сказано ничего"}
        pair_verdicts = {c: {"status": PAIRING_UNMEASURED, "tried": 0,
                             "answered_by": [], "pairings": [],
                             "reason": pair_meta["reason"]}
                         for c in blind_everywhere}

    for row in rows:
        criterion = row["criterion"]
        if criterion not in pair_verdicts:
            row["pairing"] = {
                "status": PAIRING_NOT_ASKED, "tried": 0, "answered_by": [],
                "pairings": [],
                "reason": ("критерий слепым во ВСЕХ деревьях не оказался — вопрос о "
                           "сборном дереве не стои́т; это НЕ «спросили и не нашли»")}
            continue
        axis = pair_verdicts[criterion]
        row["pairing"] = axis
        if axis["status"] == PAIRING_ANSWERED:
            named = " · ".join(f"поверхности {a['surfaces']} × артефакты "
                               f"{a['data_dir']} ⇒ {a['probe_verdict']}"
                               for a in axis["answered_by"])
            # Прежний вердикт о ДЕРЕВЬЯХ не стирается: он верен и несёт причины
            # по каждому дереву. Меняется ответ на вопрос «есть ли ответ вообще».
            row["blind_detail"] = row["detail"]
            row["verdict"] = ANSWERABLE_BY_PAIRING
            row["detail"] = (
                f"ни одно ОДИНОЧНОЕ дерево не ответило, а СБОРНАЯ ПАРА ответила: "
                f"{named}. Критерий ОТВЕТИМ, и «слепы все деревья» концом вопроса не "
                f"является; дерева с такой парой НЕ СУЩЕСТВУЕТ — замер сборный. "
                f"Слепота по деревьям: {row['blind_detail']}")
        elif axis["status"] == PAIRING_BLIND:
            row["detail"] = (f"{row['detail']} || ОСЬ СБОРНОЙ ПАРЫ СПРОШЕНА и тоже "
                             f"слепа ({axis.get('tried')} пар(ы)) ⇒ причина есть "
                             f"свойство МИРА, а не дерева")
        else:
            row["detail"] = (f"{row['detail']} || ось сборной пары НЕ ИЗМЕРЕНА: "
                             f"{axis.get('reason', 'причина не названа')}")

    counts = {v: 0 for v in VERDICTS}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    pairing_counts = {s: 0 for s in PAIRING_STATES}
    for row in rows:
        state = (row.get("pairing") or {}).get("status")
        pairing_counts[state] = pairing_counts.get(state, 0) + 1

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
            "pairing_counts": pairing_counts, "pairing_axis": pair_meta,
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
    lines += _pairing_lines(doc)
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
                 "правильный ответ) · ВКЛАД КАЖДОЙ из разных причин по отдельности "
                 "(ось сборной пары отвечает о паре ЦЕЛИКОМ, а не о разложении "
                 "слепоты) · полноту перечня деревьев (он объявлен, а не найден "
                 "обходом диска) · существование дерева, равного сборной паре — "
                 "такого дерева НЕТ, и ответ пары местом приёмки не является")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False)")
    return lines


def _pairing_lines(doc: dict) -> list[str]:
    """Ось сборной пары печатается ВСЕГДА, в том числе когда её не спрашивали.

    Молчащая ось неотличима от оси, не нашедшей ничего, — ровно тот дефект, против
    которого инвариант #17. Поэтому строка есть и у «вопрос не стои́т», и у
    «выключена входом», и цена оси печатается числом, а не словом «дорого».
    """
    axis = observed(doc, "pairing_axis", kind=dict)
    counts = observed(doc, "pairing_counts", kind=dict)
    if axis is None or counts is None:
        return ["  ось СБОРНОЙ ПАРЫ: НЕ ИЗМЕРЕНА — вердикт снят прибором без этой "
                "оси, и ноль её находок утверждением о парах не является"]
    head = ("  ось СБОРНОЙ ПАРЫ (поверхности из одного дерева × артефакты из "
            "другого): " + " · ".join(f"{s} {counts.get(s, 0)}" for s in PAIRING_STATES))
    lines = [head]
    lines.append(f"     пар объявлено {axis.get('pairings_declared')} при потолке "
                 f"{axis.get('cap')} · слепых повсюду критериев "
                 f"{axis.get('blind_population')} · цена оси "
                 f"{axis.get('seconds')} с"
                 + (f" · {axis['reason']}" if axis.get("reason") else ""))
    for pair in axis.get("pairings") or ():
        lines.append(f"     [пара] поверхности {pair.get('surfaces')} × артефакты "
                     f"{pair.get('data_dir')} — {pair.get('state')}"
                     + (f": {pair['reason']}" if pair.get("reason") else ""))
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
    ap.add_argument("--no-pairings", action="store_true",
                    help="НЕ спрашивать сборные пары о слепых повсюду критериях "
                         "(каждая пара — отдельный прогон настоящих проб, ≈42 с). "
                         "Выключенная ось отвечает «НЕ ИЗМЕРЕНО» с причиной, а не "
                         "молчит")
    args = ap.parse_args(argv)

    try:
        doc = measure(args.repo_root, trees=args.tree, ref=args.ref,
                      pairings=not args.no_pairings)
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
