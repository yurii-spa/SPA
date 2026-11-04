#!/usr/bin/env python3
"""Родословная ОБЪЯВЛЕННОГО дерева-приёмки §49: на чьём коде оно стои́т и можно ли его пересобрать.

Решение владельца **ADR-509** (вариант 1) завело отдельное дерево только для
чтения, в котором сходятся поверхности владельца и живые артефакты. Дерево на
диске есть с 15.10. Замер 2026-11-04 (цикл #1031) спросил у него вопросы,
которых до сих пор не задавал никто (ПОЛНЫЙ клон, `~/Documents/SPA_mirror`):

| вопрос | ответ |
|---|---|
| чем дерево пересобирается? | маркер называет `scripts/build_acceptance_tree.py` — файла **НЕ БЫЛО НИКОГДА** ни на одной ветке (`git log --all` пуст в ПОЛНОМ клоне) |
| на каком коде оно стои́т? | `167667598` — предок `main`, отставание **519** коммитов |
| та ли это мерка §49? | **НЕТ:** за 519 коммитов изменились `card_acceptance.py` (+7699/−63 — там живут сами пробы §49) и `cio_acceptance_rollup.py` (+98/−1) |
| кто его читает? | НИКТО: слова `SPA_acceptance` нет ни в одном файле `origin/main` |

То есть место приёмки приказа владельца было **невоспроизводимо**, отвечало бы
**прошлой меркой** и **не имело читателя** — а выглядело исполненным, потому что
каталог на диске есть. Единственный прибор о деревьях приёмки
(:mod:`spa_core.monitoring.acceptance_tree_capability`) мерит прод и зеркало, а
про объявленное дерево не спрашивает вовсе.

## Первая редакция этого прибора соврала — и это главная находка цикла

Написанный утром прибор объявил дерево ``diverged``: «коммит НЕ предок
`origin/main`, его содержит ровно одна ссылка — невлитой
`candidate/adr762-version-bound`». Звучало как находка и было **ЛОЖЬЮ**.

Причина — в клоне, у которого спросили. Прод-клон `~/Documents/SPA_Claude`
(и КАЖДЫЙ его worktree) **УСЕЧЁН**: `rev-parse --is-shallow-repository` = `true`,
17 границ в `.git/shallow`, от `origin/main` достижимо **252** коммита против
**28 011** в полном клоне — 99 % истории там просто нет. На таком графе
`merge-base --is-ancestor` отвечает «не предок», а `for-each-ref --contains` —
«только кандидатная ветка», **кодом возврата 0 и без единого предупреждения**.
Ошибка идёт в ОПАСНУЮ сторону: усечение РОЖДАЕТ находку, которой нет.

Поэтому клон здесь не берётся, а ВЫБИРАЕТСЯ (:func:`pick_lineage_repo`):
порядок кандидатов объявлен, усечённый отвергается с названной причиной, выбор
печатается, ни один не подошёл ⇒ отказ. Это тот же класс, что § «GIT-ОКРУЖЕНИЕ
в тестах» в `.claude/rules/deployment.md` (глубина клона — необъявленный вход),
только дверь не у теста, а у прибора.

## Чем этот вопрос отличается от двух соседних

Приборов про §49 уже три, и каждый отвечает на свой вопрос:

| вопрос | кто отвечает |
|---|---|
| ВЫПОЛНЕН ли критерий? | `scripts/cio_acceptance_rollup.py` (ADR-505) |
| СПОСОБНО ли дерево вынести вердикт? | `acceptance_tree_capability` (ADR-545) |
| **имеет ли объявленное дерево право быть местом приёмки?** | этот прибор |

Различие существенно: оба соседа судят о деревьях, которые им НАЗВАЛИ, и
«ответило» у них значит «проба отработала». Проба отрабатывает и на коде
двадцатидневной давности, стоящем на невлитой кандидатной ветке — отрабатывает
молча и с тем же словом «ответило». Родословная места приёмки есть отдельное
свойство, и ни один из соседей его не спрашивает.

## Шесть исходов, и они не сводятся друг к другу (инв. #17)

| исход | что это значит |
|---|---|
| ``on_ref`` | коммит маркера — предок объявленной ссылки, и носители мерки §49 на нём ТЕ ЖЕ |
| ``behind_on_measure`` | предок, но сама мерка §49 с тех пор изменилась — дерево отвечает прошлой меркой |
| ``diverged`` | коммит НЕ предок ссылки: место приёмки стои́т на коде, которого на `main` нет |
| ``not_rebuildable`` | сборщик, названный маркером, в репозитории отсутствует — дерево невоспроизводимо |
| ``data_is_a_copy`` | ``data`` в дереве не ссылка на живой каталог, а копия: она устареет МОЛЧА |
| ``unmeasured`` | маркера нет / не читается / git не ответил / коммита нет в хранилище — причина НАЗВАНА |

``behind_on_measure`` отделён от «просто позади» намеренно. Отставание само по
себе дефектом не является: дерево приёмки и не обязано догонять каждый коммит.
Дефект — отставание ИМЕННО НОСИТЕЛЕЙ МЕРКИ: тогда «критерий не выполнен»
означает «не выполнен по прошлогодней мерке», и прочесть одно как другое нельзя.
Поэтому число отставания печатается всегда, а находкой становится лишь
изменившаяся мерка.

``not_rebuildable`` и ``diverged`` НЕ поглощают друг друга: сборщик может
существовать у дерева, стоящего не на `main` (его позвали с чужой ссылкой), и
наоборот — дерево на верном коммите может быть собрано скриптом, которого никто
не закоммитил. Это два разных дефекта, и лечатся они разным.

## Носители мерки §49 ОБЪЯВЛЕНЫ, а не найдены обходом

Перечень :data:`MEASURE_CARRIERS` — объявление, и это сказано вслух. Импортное
замыкание проб §49 здесь не обходится намеренно: оно тянет половину
`spa_core/`, и «мерка изменилась» срабатывало бы на каждом коммите, то есть
перестало бы что-либо означать. Цена объявления названа честно: носитель, не
попавший в перечень, этим прибором не измеряется, и нулём это не считается —
исход ``on_ref`` утверждает ровно про объявленные пути.

## Чего прибор НЕ докладывает

* **Верность ответов дерева.** «Дерево стои́т на `main`» не значит «его вердикт
  §49 верен»: правду мерки держит её собственный контроль в обе стороны
  (`.claude/rules/acceptance.md`, п. 3).
* **Свежесть `data`.** Прибор спрашивает, ССЫЛКА это или копия, а не «сколько
  часов артефакту»: возраст живых артефактов меряют их собственные сторожа.
* **Полноту перечня деревьев.** Дерево ОБЪЯВЛЕНО (CLI / умолчание), а не найдено
  обходом диска — тот же договор, что у :mod:`acceptance_tree_capability`.
* **Был ли коммит маркера на `main` КОГДА-ТО.** Вопрос задаётся о сегодняшней
  ссылке; история её переписываний здесь не разбирается.

ADVISORY: прибор только ЧИТАЕТ. Ни строки risk-логики, RiskPolicy, стоп-крана,
аллокатора, живого трека или `landing/**`. Дерева он не собирает и не правит —
сборка живёт в `scripts/build_acceptance_tree.py`, и вызвать её прибор не может
по построению.

## Коды возврата

* **0** — замер состоялся, находок нет.
* **1** — замер состоялся, находки НАЗВАНЫ.
* **2** — замера нет вовсе: причина названа, про место приёмки НЕ СКАЗАНО НИЧЕГО.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "acceptance_tree_lineage.json"

#: Имя маркера в корне дерева-приёмки. Его пишет сборщик, его читает этот прибор —
#: ОДНА форма на двоих, второй копии договора нет.
MARKER_NAME = ".acceptance_tree.json"

#: Объявленное дерево-приёмка (решение владельца ADR-509, вариант 1).
ACCEPTANCE_TREE_DEFAULT = str(Path.home() / "Documents" / "SPA_acceptance")

#: Ссылка, относительно которой судится родословная. `main` здесь не случайна:
#: место приёмки приказа обязано стоять на коде, который ПРИНЯТ, а не на
#: кандидате — иначе приёмка мерит то, чего в системе нет.
REF_DEFAULT = "origin/main"

#: Зеркало источников на Маке (ADR-152) — ПОЛНЫЙ клон, и это его здесь свойство,
#: а не удобство: прод-клон УСЕЧЁН (замер ниже), и спрашивать родословную у него
#: нельзя вовсе.
MIRROR_DEFAULT = str(Path.home() / "Documents" / "SPA_mirror")

#: Пути, несущие МЕРКУ §49. Объявление, не обход (см. шапку).
MEASURE_CARRIERS = (
    "scripts/cio_acceptance_rollup.py",
    "spa_core/monitoring/card_acceptance.py",
    "spa_core/monitoring/s49_criterion_price.py",
    "spa_core/monitoring/probe_verdict_authorship.py",
    "spa_core/monitoring/acceptance_tree_capability.py",
    "spa_core/monitoring/s49_tally_tact.py",
)

#: Такт замера. Предмет — КОНФИГУРАЦИЯ дерева приёмки, она меняется не ежечасно;
#: тот же договор и тот же читатель такта, что у соседа (ADR-220: вторая копия
#: гейта такта разошлась бы молча).
MEASUREMENT_TACT_DAYS = 7

ON_REF = "on_ref"
BEHIND_ON_MEASURE = "behind_on_measure"
DIVERGED = "diverged"
NOT_REBUILDABLE = "not_rebuildable"
DATA_IS_A_COPY = "data_is_a_copy"
UNMEASURED = "unmeasured"

#: Порядок ПЕЧАТИ. Порядок СТАРШИНСТВА другой и живёт в :func:`_tree_row`:
#: ``diverged`` → ``behind_on_measure`` → ``not_rebuildable`` → ``data_is_a_copy``.
#: Первым спрашивается происхождение, потому что у дерева ВНЕ принятого кода
#: остальные вопросы меняют смысл: «сборщик есть» и «мерка та же» утверждались бы
#: про чужую ветку. Вердикт у строки один (самый старший), но ВСЕ наблюдения
#: (`builder_present`, `carriers_changed`, `data_binding`) лежат в ней всегда —
#: иначе старший вердикт прятал бы младшие, и починка одного открывала бы второй
#: как новость.
VERDICTS = (ON_REF, BEHIND_ON_MEASURE, DIVERGED, NOT_REBUILDABLE,
            DATA_IS_A_COPY, UNMEASURED)

#: Находка = дефект места приёмки. ``on_ref`` находкой не является; ``unmeasured``
#: тоже не является — он не утверждение о дереве, а отказ судить, и считать его
#: находкой значило бы печатать дефект тем громче, чем хуже своя конфигурация.
FINDING_VERDICTS = (BEHIND_ON_MEASURE, DIVERGED, NOT_REBUILDABLE, DATA_IS_A_COPY)

VERDICT_RU = {
    ON_REF: "дерево стои́т на принятом коде, мерка §49 та же",
    BEHIND_ON_MEASURE: "дерево отстаёт ИМЕННО носителями мерки §49 — вердикт снят прошлой меркой",
    DIVERGED: "коммит дерева НЕ на объявленной ссылке — место приёмки стои́т вне принятого кода",
    NOT_REBUILDABLE: "сборщика, названного маркером, в репозитории НЕТ — дерево невоспроизводимо",
    DATA_IS_A_COPY: "`data` в дереве КОПИЯ, а не ссылка — она устареет молча",
    UNMEASURED: "судить было нечем — причина названа",
}


class Unmeasured(Exception):
    """Замера нет вовсе. Несёт причину, которую обязан напечатать вызывающий."""


def _git(repo: Path, *args: str, timeout: float = 30.0) -> tuple[int, str]:
    """Один вопрос к git. Возвращает (код, вывод) — исключение сюда не доходит.

    Код возврата НЕ склеивается с пустым выводом: «git ответил пусто» и «git не
    ответил» суть разные исходы, и решать, какой из них перед ним, обязан
    вызывающий (инв. #17).
    """
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"git не позван: {exc}"
    return proc.returncode, (proc.stdout or "").strip()


def history_completeness(repo: Path) -> dict:
    """Способен ли клон вообще отвечать на вопрос о происхождении коммита.

    **Это не аккуратность, а условие осмысленности вопроса, и цена измерена.**
    Замер 2026-11-04 (цикл #1031, тот же, что написал этот прибор): прод-клон
    `~/Documents/SPA_Claude` — **УСЕЧЁННЫЙ** (`rev-parse
    --is-shallow-repository` = `true`, 17 границ в `.git/shallow`). От его
    `origin/main` достижимо **252** коммита; настоящая история того же `main` в
    полном клоне — **28 011**. То есть 99 % истории в прод-клоне просто нет.

    И git об этом НЕ ГОВОРИТ. На усечённом графе `merge-base --is-ancestor`
    отвечает «не предок», а `for-each-ref --contains` — «содержит только
    кандидатная ветка», кодом возврата 0 и без единого предупреждения. Первая
    редакция этого прибора так и объявила дерево-приёмку `diverged`; настоящий
    ответ, снятый в полном клоне, — предок, отставание 519 коммитов. Ошибка шла
    в ОПАСНУЮ сторону: усечение графа РОЖДАЕТ находку, которой нет.

    Это тот же класс, что § «GIT-ОКРУЖЕНИЕ в тестах» в
    `.claude/rules/deployment.md` (глубина клона — необъявленный вход, `fetch-depth`
    по умолчанию 1), только дверь не у теста, а у прибора.

    Три исхода различимы (инв. #17): клон ПОЛНЫЙ · клон УСЕЧЁН · git не ответил.
    """
    code, out = _git(repo, "rev-parse", "--is-shallow-repository")
    if code != 0 or out not in ("true", "false"):
        return {"state": "unmeasured",
                "reason": (f"git не ответил, усечён ли клон {repo}: "
                           f"{out or 'пусто'} (код {code})")}
    reachable = _count(repo, "HEAD")
    if out == "true":
        return {"state": "shallow", "reachable_from_head": reachable,
                "reason": (f"клон {repo} УСЕЧЁН (shallow): от HEAD достижимо "
                           f"{reachable} коммит(ов). На усечённом графе ответ "
                           f"«не предок» НЕОТЛИЧИМ от «предок, которого здесь "
                           f"нет», и git об этом молчит")}
    return {"state": "complete", "reachable_from_head": reachable}


def pick_lineage_repo(candidates: Sequence[str]) -> tuple[Path, list[dict]]:
    """Первый ПОЛНЫЙ клон из объявленного порядка — и перечень отвергнутых.

    Порядок ОБЪЯВЛЕН, а выбор ПЕЧАТАЕТСЯ: это не угадывание клона, а отказ
    спрашивать родословную у того, кто не может ответить. Молча подставить
    второй клон было бы хуже ошибки — читатель не узнал бы, о чьём `main` ему
    ответили.
    """
    rejected: list[dict] = []
    for name in candidates:
        repo = Path(name)
        if not repo.exists():
            rejected.append({"repo": str(repo), "state": "absent",
                             "reason": f"клона нет на диске: {repo}"})
            continue
        verdict = history_completeness(repo)
        if verdict["state"] == "complete":
            return repo, rejected
        rejected.append({"repo": str(repo), **verdict})
    raise Unmeasured(
        "ни один объявленный клон не способен ответить о происхождении коммита: "
        + " · ".join(f"{r['repo']} — {r.get('reason', r.get('state'))}"
                     for r in rejected)
        + ". Про место приёмки §49 НЕ СКАЗАНО НИЧЕГО")


def read_marker(tree: Path) -> dict:
    """Маркер дерева-приёмки. Отсутствие и нечитаемость — РАЗНЫЕ причины отказа."""
    path = Path(tree) / MARKER_NAME
    if not Path(tree).exists():
        raise Unmeasured(f"дерева нет на диске: {tree}")
    if not path.exists():
        raise Unmeasured(
            f"в дереве {tree} нет маркера {MARKER_NAME}: деревом приёмки его "
            f"объявил кто-то вне этого прибора, и чем оно собрано — не записано")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Unmeasured(f"маркер {path} не читается: {exc}") from exc
    if not isinstance(doc, dict):
        raise Unmeasured(f"маркер {path} не является объектом: {type(doc).__name__}")
    return doc


def _data_binding(tree: Path, marker: dict) -> dict:
    """ССЫЛКА ли `data` в дереве — или копия, которая устареет молча.

    Вопрос задаётся ДИСКУ, а не маркеру: маркер объявляет замысел («data — ССЫЛКА
    на живой каталог»), и сверять объявление с собой же значило бы получить
    зелёный по построению.
    """
    data = Path(tree) / "data"
    declared = observed(marker, "live_data", kind=str)
    if not data.exists():
        return {"state": "absent", "declared": declared,
                "detail": f"каталога {data} нет вовсе"}
    if data.is_symlink():
        target = os.path.realpath(str(data))
        same = bool(declared) and os.path.realpath(str(declared)) == target
        return {"state": "symlink", "target": target, "declared": declared,
                "matches_declared": same,
                "detail": (f"ссылка → {target}"
                           + ("" if same else
                              f"; объявлено было {declared!r} — РАСХОДИТСЯ"))}
    return {"state": "copy", "declared": declared,
            "detail": (f"{data} — настоящий каталог, не ссылка: его содержимое "
                       f"устареет молча, и отличить устаревшее от живого будет нечем")}


def measure(repo_root: str | Path = _REPO_ROOT, *,
            trees: Optional[Sequence[str]] = None,
            ref: str = REF_DEFAULT, repos: Optional[Sequence[str]] = None,
            now=None, tree_root: Optional[Path] = None) -> dict:
    """Замер родословной каждого ОБЪЯВЛЕННОГО дерева-приёмки.

    ``repo_root`` — первый кандидат на роль клона, у которого спрашивают про
    ссылку, про происхождение коммита и про наличие сборщика. Само дерево-приёмка
    при этом может быть любым каталогом и своей истории не иметь (оно и не имеет:
    ADR-509 велел сделать его только для чтения, а не рабочей копией).

    **Клон выбирается, а не берётся.** Усечённый клон на вопрос о происхождении
    отвечает НЕВЕРНО и молча (см. :func:`history_completeness`), поэтому порядок
    кандидатов объявлен — своё дерево, затем полное зеркало источников, — а
    выбранный клон и все отвергнутые ПЕЧАТАЮТСЯ. Ни один не подошёл ⇒ отказ.
    """
    declared = list(trees) if trees is not None else [ACCEPTANCE_TREE_DEFAULT]
    if not declared:
        raise Unmeasured("деревьев не объявлено ни одного — судить не о чем")

    candidates = (list(repos) if repos is not None
                  else [str(repo_root), MIRROR_DEFAULT])
    repo, rejected = pick_lineage_repo(candidates)
    # Признак ЗВАВШЕГО берётся у ПРОЦЕССА, а не передаётся параметром: переданный
    # звавший есть собственное утверждение ступени о себе, и она объявила бы себя
    # ступенью и тогда, когда её никто не звал. Без этой записи вопрос «отметку
    # поставила СТУПЕНЬ или чья-то РУКА» неизмерим ПО ПОСТРОЕНИЮ — `generated_at`
    # есть ЧАСЫ и сменится ОДИНАКОВО в оба случая (ADR-805, заказ G804 п. 3).
    invoked_by = call_provenance(
        tree_root=tree_root if tree_root is not None else Path(repo_root))

    code, ref_sha = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if code != 0 or not ref_sha:
        raise Unmeasured(
            f"ссылка {ref!r} не разрешается в дереве {repo}: {ref_sha or 'git молчит'}. "
            f"Без неё «на ссылке ли коммит дерева» не вопрос, а догадка")

    rows = [_tree_row(repo, Path(tree), ref=ref, ref_sha=ref_sha)
            for tree in declared]

    counts = {v: 0 for v in VERDICTS}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    findings = sum(counts.get(v, 0) for v in FINDING_VERDICTS)
    return {"status": "OK", "generated_at": _stamp_now(now),
            "invoked_by": invoked_by,
            "repo_root": str(repo), "ref": ref, "ref_sha": ref_sha,
            "repo_candidates": [str(c) for c in candidates],
            "repo_rejected": rejected,
            "repo_history": history_completeness(repo),
            "population": len(rows), "rows": rows, "counts": counts,
            "trees_declared": [str(t) for t in declared],
            "measure_carriers": list(MEASURE_CARRIERS),
            "findings": findings}


def _tree_row(repo: Path, tree: Path, *, ref: str, ref_sha: str) -> dict:
    """Одно дерево: вердикт, его причина и все числа, которыми он добыт."""
    row: dict = {"tree": str(tree), "ref": ref}
    try:
        marker = read_marker(tree)
    except Unmeasured as exc:
        row.update({"verdict": UNMEASURED, "detail": str(exc)})
        return row

    row["marker"] = {k: marker.get(k) for k in
                     ("version", "built_at", "ref", "commit", "builder",
                      "source_repo", "live_data", "read_only")}
    row["data_binding"] = _data_binding(tree, marker)

    builder_rel = observed(marker, "builder", kind=str)
    if not builder_rel:
        # Маркер первой редакции сборщика не называл — его называла `note`.
        # Разбирать прозу ради имени файла прибор не станет: это была бы догадка
        # о намерении автора, а не замер. Исход назван отдельно.
        builder_rel = _builder_named_in_note(marker)
    row["builder_declared"] = builder_rel
    builder_present = bool(builder_rel) and (repo / builder_rel).exists()
    row["builder_present"] = builder_present if builder_rel else None

    commit = observed(marker, "commit", kind=str)
    if not commit:
        row.update({"verdict": UNMEASURED,
                    "detail": (f"маркер {tree}/{MARKER_NAME} не называет коммита: "
                               f"на чьём коде стои́т дерево, не записано вовсе")})
        return row

    code, resolved = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}")
    if code != 0 or not resolved:
        row.update({"verdict": UNMEASURED,
                    "detail": (f"коммита {commit} нет в хранилище {repo}: "
                               f"предок он объявленной ссылке или нет — НЕ ИЗМЕРЕНО, "
                               f"и нулём это не считается")})
        return row
    row["commit"] = resolved

    is_ancestor, _ = _git(repo, "merge-base", "--is-ancestor", resolved, ref_sha)
    row["on_ref"] = (is_ancestor == 0)
    row["behind"] = _count(repo, f"{resolved}..{ref_sha}")
    row["ahead"] = _count(repo, f"{ref_sha}..{resolved}")
    row["refs_containing"] = _refs_containing(repo, resolved)

    if is_ancestor != 0:
        where = (", ".join(row["refs_containing"]) if row["refs_containing"]
                 else "НИ ОДНА ссылка его не содержит")
        row.update({"verdict": DIVERGED, "detail": (
            f"коммит {resolved[:9]} НЕ предок {ref} ({ref_sha[:9]}): у {ref} "
            f"{row['behind']} коммит(ов), которых нет у дерева, и {row['ahead']} "
            f"наоборот. Содержат его: {where}. Маркер при этом объявляет "
            f"ref={marker.get('ref')!r}")})
        return row

    changed = _changed_carriers(repo, resolved, ref_sha)
    row["carriers_changed"] = changed
    if changed:
        row.update({"verdict": BEHIND_ON_MEASURE, "detail": (
            f"коммит {resolved[:9]} — предок {ref}, но отстаёт на "
            f"{row['behind']} коммит(ов), и среди них изменились носители мерки "
            f"§49: {', '.join(changed)}. Вердикт, снятый в этом дереве, снят "
            f"ПРОШЛОЙ меркой")})
        return row

    if builder_rel and not builder_present:
        row.update({"verdict": NOT_REBUILDABLE, "detail": (
            f"маркер называет сборщик {builder_rel}, а в {repo} такого файла нет: "
            f"дерево на верном коммите, но пересобрать его нечем — следующий замер "
            f"придётся делать на том же устаревающем коде")})
        return row
    if not builder_rel:
        row.update({"verdict": NOT_REBUILDABLE, "detail": (
            f"маркер {tree}/{MARKER_NAME} не называет сборщика ни полем `builder`, "
            f"ни именем файла в `note`: чем пересобрать дерево — не записано")})
        return row

    if row["data_binding"]["state"] == "copy":
        row.update({"verdict": DATA_IS_A_COPY,
                    "detail": row["data_binding"]["detail"]})
        return row

    row.update({"verdict": ON_REF, "detail": (
        f"коммит {resolved[:9]} — предок {ref}; отставание {row['behind']} "
        f"коммит(ов) носителей мерки §49 не задело; сборщик {builder_rel} в дереве "
        f"есть; `data` — {row['data_binding']['detail']}")})
    return row


def _builder_named_in_note(marker: dict) -> Optional[str]:
    """Имя сборщика из прозы `note` — только если оно там названо ПУТЁМ.

    Берётся не «похожее слово», а токен, выглядящий путём к питонному файлу под
    `scripts/`. Не нашлось ⇒ ``None``: выдумать имя значило бы ответить на
    вопрос, которого маркер не задавал.
    """
    note = observed(marker, "note", kind=str) or ""
    for token in note.replace("`", " ").split():
        token = token.strip(".,;:()")
        if token.startswith("scripts/") and token.endswith(".py"):
            return token
    return None


def _count(repo: Path, span: str) -> Optional[int]:
    """Сколько коммитов в промежутке. ``None`` = git не ответил, а не ноль."""
    code, out = _git(repo, "rev-list", "--count", span)
    if code != 0 or not out:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def _refs_containing(repo: Path, sha: str) -> list[str]:
    """Ссылки, содержащие коммит. Пустой список — ЗАМЕР («ни одна»), не отказ."""
    code, out = _git(repo, "for-each-ref", f"--contains={sha}",
                     "--format=%(refname)")
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _changed_carriers(repo: Path, old: str, new: str) -> list[str]:
    """Носители мерки §49, изменившиеся между двумя коммитами.

    Спрашивается ПОИМЁННО по объявленному перечню, а не `diff --name-only` по
    всему дереву: второй ответил бы «изменилось всё» на любом промежутке в
    двести коммитов, то есть не ответил бы ни о чём.
    """
    changed: list[str] = []
    for rel in MEASURE_CARRIERS:
        code, out = _git(repo, "diff", "--name-only", f"{old}..{new}", "--", rel)
        if code == 0 and out:
            changed.append(rel)
    return changed


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
        # навсегда — «не смогли прочитать, когда мерили» означает «мерим».
        # Запись о звавшем — тоже: у отказа вопрос «ступень или рука» важнее
        # всего, а отметка `generated_at` на него не отвечает (ADR-805).
        doc = {"status": "UNMEASURED", "reason": str(exc),
               "invoked_by": call_provenance(tree_root=root),
               "generated_at": _stamp_now(now)}
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def report(doc: dict, max_rows: int = 10) -> list[str]:
    lines: list[str] = []
    if str(doc.get("status")) != "OK":
        lines.append(f"НЕ ИЗМЕРЕНО: {doc.get('reason', 'причина не названа')}")
        lines.append("  про право объявленного дерева быть местом приёмки §49 "
                     "НЕ СКАЗАНО НИЧЕГО — выдать это за «право есть» нельзя")
        return lines
    counts = observed(doc, "counts", kind=dict) or {}
    history = observed(doc, "repo_history", kind=dict) or {}
    lines.append(
        f"Родословная места приёмки §49 (ADR-509): деревьев объявлено "
        f"{doc.get('population')}, ссылка {doc.get('ref')} "
        f"({str(doc.get('ref_sha') or '')[:9]})")
    lines.append(
        f"  спрошен клон {doc.get('repo_root')} — история {history.get('state')}, "
        f"от HEAD достижимо {history.get('reachable_from_head')} коммит(ов)")
    for row in doc.get("repo_rejected") or ():
        lines.append(f"  ⚠️  клон ОТВЕРГНУТ: {row.get('reason', row.get('state'))}")
    lines.append("  " + " · ".join(f"{v} {counts.get(v, 0)}" for v in VERDICTS))
    shown = 0
    for row in doc.get("rows") or ():
        if shown >= max_rows:
            break
        mark = "✅" if row["verdict"] == ON_REF else (
            "⚠️" if row["verdict"] == UNMEASURED else "❗")
        lines.append(f"  {mark} [{row['verdict']}] {row['tree']} — {row['detail']}")
        shown += 1
    rest = int(doc.get("population") or 0) - shown
    if rest > 0:
        lines.append(f"  … ещё {rest} дерев(о/а) (полный перечень — `--json`)")
    lines.append("  носители мерки §49 ОБЪЯВЛЕНЫ, а не найдены обходом: "
                 + ", ".join(doc.get("measure_carriers") or ()))
    lines.append("  НЕ ДОКЛАДЫВАЕТ: верность ответов дерева (стои́т на `main` ≠ "
                 "отвечает правильно) · свежесть `data` (спрошено «ссылка или "
                 "копия», не «сколько часов») · полноту перечня деревьев (он "
                 "объявлен, а не найден обходом диска) · был ли коммит маркера "
                 "на ссылке КОГДА-ТО")
    lines.append("  ADVISORY: прибор только ЧИТАЕТ (applied=False) — дерева он не "
                 "собирает и не правит")
    return lines


def format_report(doc: dict, max_rows: int = 5) -> list[str]:
    """Отрисовка для шага 0-офис. Правило отрисовки живёт У ПРОИЗВОДИТЕЛЯ — вторая
    копия у читателя разошлась бы с ним молча (ADR-220)."""
    head = ["— родословная места приёмки §49 приказа «Portfolio CIO» (ADR-918) —"]
    return head + ["   " + line for line in report(doc, max_rows=max_rows)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=str(_REPO_ROOT),
                    help="репозиторий, у которого спрашивают ссылку и сборщик")
    ap.add_argument("--repo", action="append", default=None,
                    help="клон-кандидат для вопроса о происхождении (можно "
                         "повторять). Умолчание — своё дерево, затем полное "
                         f"зеркало {MIRROR_DEFAULT}; УСЕЧЁННЫЙ отвергается")
    ap.add_argument("--tree", action="append", default=None,
                    help="дерево-приёмка (можно повторять). Умолчание — "
                         f"{ACCEPTANCE_TREE_DEFAULT}")
    ap.add_argument("--ref", default=REF_DEFAULT)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--max-rows", type=int, default=10)
    args = ap.parse_args(argv)

    try:
        doc = measure(args.repo_root, trees=args.tree, ref=args.ref,
                      repos=args.repo)
    except Unmeasured as exc:
        doc = {"status": "UNMEASURED", "reason": str(exc),
               "generated_at": _stamp_now()}
    if not args.no_write:
        dest = (Path(args.out) if args.out
                else Path(args.repo_root) / "data" / ARTIFACT)
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
