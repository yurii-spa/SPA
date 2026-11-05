#!/usr/bin/env python3
"""Перепись СИРОТ: готовая работа предшественника, которая лежит вне `origin/main`.

Заказ G910 п. 1 карточки приказа «Portfolio CIO» предписывает эту перепись
**первым действием каждого цикла**: за последние циклы подъёмов было уже пять
(#1018, #1022, #1025, #1034, #1036), и сирота стои́т дороже любого нового замера —
работа сделана и ЗАКОНЧЕНА, не хватает только пуша.

## Почему для этого нужен прибор, а не строка `git` в промпте

До цикла #1036 перепись делалась руками, и у ручной формы ДВЕ разные болезни.

**Первая — дешёвая ось ОТРАВЛЕНА клоном, в котором её только и запускают.**
Прод-клон `~/Documents/SPA_Claude` и **КАЖДЫЙ его worktree** УСЕЧЕНЫ (ADR-918:
252 коммита от `origin/main` против 28 011 в полном зеркале). На усечённом графе
`merge-base --is-ancestor` отвечает «не предок» **кодом возврата 0 и без единого
предупреждения**, и ошибка идёт в ОПАСНУЮ сторону — усечение РОЖДАЕТ кандидата,
которого нет. Замер цикла #1036 на 84 деревьях прод-клона:

| ось спрошена в | кандидатов «вне main» | из них ЛОЖНЫХ |
|---|---|---|
| усечённый прод-клон | **40** | **21** (52,5 %) — полный клон говорит `on_main` |
| полное зеркало | 19 | — |

Поэтому клон здесь не берётся, а **ВЫБИРАЕТСЯ** (:func:`~spa_core.monitoring.
acceptance_tree_lineage.pick_lineage_repo`), выбор ПЕЧАТАЕТСЯ, и усечённый клон
есть **третий исход** (`unmeasured` с названной причиной), а не ответ.

**Вторая — ось «ADR-файла нет на `main`» имеет точность 1/8.** Замер ADR-922 п. 1:
8 кандидатов, 7 ложных (переименование и перенумерация при доставке), а
единственный истинный (ADR-902) подъём ЗАПРЕЩАЕТ — он отложен владельцем.
Ось этого прибора другая: **коммита дерева нет в полном клоне ВОВСЕ** (то есть
он не уезжал никуда и ни под каким именем), а размер работы меряется ПРОЛЁТОМ до
первого коммита, который на `ref` есть.

## Пять исходов, и они не сводятся друг к другу (инв. #17)

| исход | что это значит |
|---|---|
| ``on_main`` | HEAD дерева — предок `ref` в ПОЛНОМ клоне. Поднимать нечего |
| ``never_pushed`` | коммита нет в полном клоне вовсе — он не уезжал. Кандидат |
| ``off_main_branch`` | коммит в полном клоне ЕСТЬ, но `ref` его не содержит: живёт на невлитой ветке. Это не сирота, а кандидат на мерж — чужое решение |
| ``no_head`` | дерево без HEAD (битое/пустое). Не ответ и не «чисто» |
| ``unmeasured`` | git не ответил, либо ни один объявленный клон не способен отвечать |

**Размер работы — отдельный вопрос с отдельным третьим исходом.** У
``never_pushed`` считается ПРОЛЁТ: сколько коммитов от HEAD по первым родителям
до первого, который в полном клоне есть И является предком `ref`. Считать пролёт
в самом усечённом дереве нельзя — там он врёт теми же 23 283 коммитами, которыми
усечение раздувает древние расхождения. Не дошли за :data:`SPAN_LIMIT` шагов ⇒
``span`` есть ``None`` и ``span_state="unmeasured"``, а НЕ число: у древнего дерева
с чужой историей размер работы не измерен, и выдать его нулём или пределом
значило бы ровно тот дефект, против которого прибор написан.

**«Пролёт 1» — самая дорогая форма:** один коммит поверх текущей вершины `ref`
есть ровно та форма, которую оставляет цикл, доделавший работу и не успевший
запушить. Замер #1036: из 13 деревьев ``never_pushed`` пролёт измерен у **3**,
и все три несли ОДИН предмет — ADR-922 цикла #1035, настоящую сироту. Остальные
10 — древние расхождения, у них ``span_state="unmeasured"``.
Точность формы на этом замере 1/1, и **это не доля, а единственное наблюдение**.

## Чего прибор НЕ умеет

Он не находит СВОЮ сироту: цикл, не запушивший свою работу, невидим для своей же
переписи ПО ПОСТРОЕНИЮ — его ADR существует только в его дереве, а перепись
кончается вместе с ним. Именно так ADR-922 п. 1 верно ответил «ни одного
настоящего подъёма» и сам стал сиротой через минуты. Эту дыру закрывает не
прибор, а СЛЕДУЮЩИЙ цикл.

Он не судит, ГОДНА ли найденная работа к подъёму: ADR-902 — настоящая сирота,
подъём которой есть предмет №1 границы ADR-285 (ответ владельца назвал цену
отдельно). Прибор НАЗЫВАЕТ кандидата; решение — за читателем.

Он не читает рабочее дерево: грязные файлы считаются (``dirty``), но
незакоммиченная работа сиротой здесь не зовётся — у неё нет коммита, а значит нет
и предмета, который можно было бы сверить с полным клоном.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring.acceptance_tree_lineage import (  # noqa: E402
    MIRROR_DEFAULT,
    Unmeasured,
    _git,
    pick_lineage_repo,
)
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402

#: Артефакт замера. Его читает шаг 0-офис поимённой веткой — без читателя
#: прибор был бы ровно тем дефектом, который храповик
#: `test_unwired_guard_modules_ratchet.py` и ловит: «написать проверку и не
#: позвать её — то же, что не написать».
ARTIFACT = "orphan_sweep.json"

#: Ссылка, относительно которой судится сирота. `main` здесь не случайна: сирота
#: это работа, не доехавшая до ПРИНЯТОГО кода, а не до любой ветки.
REF_DEFAULT = "origin/main"

#: Порядок клонов, у которых спрашивается происхождение коммита. Зеркало ПЕРВЫМ
#: и это его свойство, а не удобство: прод-клон усечён по построению (ADR-918).
LINEAGE_CANDIDATES_DEFAULT = (MIRROR_DEFAULT, str(Path.home() / "Documents" / "SPA_Claude"))

#: Предел шагов по первым родителям при измерении пролёта. Дошли до предела ⇒
#: пролёт НЕ ИЗМЕРЕН (третий исход), а не равен пределу.
SPAN_LIMIT = 50

#: Исходы дерева. Перечень ЗАМКНУТ: новый исход обязан быть назван здесь, иначе
#: учёт перестанет сходиться (см. :func:`sweep`, тождество `tally`).
VERDICTS = ("on_main", "never_pushed", "off_main_branch", "no_head", "unmeasured")

#: Исходы, при которых дерево есть КАНДИДАТ на подъём (ненулевой код возврата).
CANDIDATE_VERDICTS = ("never_pushed",)

#: Самый загруженный СУТОЧНЫЙ поток `origin/main` в замере #1036 (10 суток,
#: 26.10–04.11): по дням 15 · 31 · 30 · 17 · 27 · 44 · **76** · 46 · 30 · 23,
#: за 7 суток 263. Это НИЖНЯЯ граница порога ниже: работа, законченная вчера,
#: за ночь отстаёт ровно на столько, и звать её «не свежей» значило бы
#: ПРОПУСТИТЬ сироту.
MEASURED_BUSIEST_DAY_ON_REF = 76

#: Ближайшее отставание базы среди ЗАБРОШЕННЫХ деревьев того же замера:
#: 971 (`studio-os-scratch/v03`) · 3101 (прод-дерево) · 4737 (`b71dde9e2`,
#: база от 2026-06-30). Это ВЕРХНЯЯ граница порога.
MEASURED_NEAREST_ABANDONED = 971

#: Насколько БАЗА кандидата вправе отставать от вершины `ref`, чтобы работа
#: считалась СВЕЖЕЙ.
#:
#: **Порог написан по ДВУМ ошибкам, и обе нашёл прибор, а не глаз.**
#:
#: Первая: рука цикла #1036 сочла разделителем ПРОЛЁТ («ровно один коммит вне
#: main»), сосчитав его в УСЕЧЁННОМ прод-клоне, где он врёт — тот же
#: `b71dde9e2` там дал 23 283, а в полном клоне его пролёт **1**. Ось
#: «пролёт 1» поймала бы восемь деревьев вместо одного и совпала с правдой
#: СЛУЧАЙНО. Разделяет не пролёт, а ОТСТАВАНИЕ БАЗЫ, измеримое только в
#: полном клоне.
#:
#: Вторая: первая редакция порога была **0** («база и есть вершина») — то есть
#: ровно та форма, которую оставила сирота #1035. И она БРИТВЕННАЯ: достаточно
#: одного автокоммита сайт-кустодиана поверх, и настоящая сирота перестала бы
#: быть «свежей» МОЛЧА, то есть порог ошибался бы в ОПАСНУЮ сторону — в
#: пропуск. Сироту #1035 спасло лишь то, что её база ещё была вершиной.
#:
#: Поэтому порог стои́т МЕЖДУ двумя ИЗМЕРЕННЫМИ населениями —
#: :data:`MEASURED_BUSIEST_DAY_ON_REF` (76) и
#: :data:`MEASURED_NEAREST_ABANDONED` (971), — и зазор между ними
#: двенадцатикратный, так что порог не на лезвии. Сторож держит именно это
#: НЕРАВЕНСТВО, а не само число: сверять число с собой значило бы мерить свою
#: же копию (урок #1027).
FRESH_BASE_LAG_MAX = 100


def worktrees(repo: Path) -> list[Path]:
    """Деревья клона. git не ответил ⇒ исключение, а не пустой список.

    Пустой список здесь был бы ровно той подменой, против которой написан
    инв. #17: «деревьев нет» неотличимо от «не спросили».
    """
    code, out = _git(repo, "worktree", "list", "--porcelain")
    if code != 0:
        raise Unmeasured(f"git не перечислил деревья клона {repo}: {out or 'пусто'} (код {code})")
    found = [Path(line[len("worktree "):]) for line in out.splitlines()
             if line.startswith("worktree ")]
    if not found:
        raise Unmeasured(f"git перечислил ноль деревьев клона {repo} — это не ответ, а молчание")
    return found


def _present(repo: Path, sha: str) -> Optional[bool]:
    """Есть ли коммит в клоне. `None` — git не ответил (не «нет»)."""
    code, _ = _git(repo, "cat-file", "-e", f"{sha}^{{commit}}")
    if code in (0, 1, 128):
        return code == 0
    return None


def _is_ancestor(repo: Path, sha: str, ref: str) -> Optional[bool]:
    """Предок ли `sha` для `ref`. `None` — git не ответил (не «нет»).

    Коды 0/1 — ответ git'а; всё остальное (нет такого ref, оборванный объект)
    есть «не измерено», и склеивать его с «не предок» запрещено: именно это
    склеивание родило ложного кандидата в первой редакции прибора ADR-918.
    """
    code, _ = _git(repo, "merge-base", "--is-ancestor", sha, ref)
    if code in (0, 1):
        return code == 0
    return None


def measure_span(tree: Path, lineage: Path, sha: str, ref: str,
                 limit: int = SPAN_LIMIT) -> dict:
    """Сколько коммитов работы несёт дерево поверх `ref`.

    Шагаем от HEAD по ПЕРВЫМ родителям, пока не встретим коммит, который в полном
    клоне есть И является предком `ref`. Число шагов до него и есть пролёт.
    Не дошли за `limit` шагов ⇒ ``unmeasured`` с названной причиной.
    """
    cur = sha
    for step in range(1, limit + 1):
        code, parents = _git(tree, "rev-list", "--parents", "-n", "1", cur)
        if code != 0:
            return {"span": None, "span_state": "unmeasured",
                    "reason": f"git не назвал родителей {cur[:9]} в {tree}: код {code}"}
        parts = parents.split()
        if len(parts) < 2:
            return {"span": None, "span_state": "unmeasured",
                    "reason": f"у {cur[:9]} нет родителя (корень истории либо граница усечения)"}
        parent = parts[1]
        present = _present(lineage, parent)
        if present is None:
            return {"span": None, "span_state": "unmeasured",
                    "reason": f"полный клон не ответил, есть ли у него {parent[:9]}"}
        if present:
            anc = _is_ancestor(lineage, parent, ref)
            if anc is None:
                return {"span": None, "span_state": "unmeasured",
                        "reason": f"полный клон не ответил, предок ли {parent[:9]} для {ref}"}
            if anc:
                lag = _count_span(lineage, f"{parent}..{ref}")
                if lag is None:
                    return {"span": step, "span_state": "measured", "base": parent,
                            "base_lag": None, "base_lag_state": "unmeasured",
                            "reason_base_lag": (f"полный клон не сосчитал, насколько {parent[:9]} "
                                                f"отстаёт от {ref}")}
                return {"span": step, "span_state": "measured", "base": parent,
                        "base_lag": lag, "base_lag_state": "measured"}
        cur = parent
    return {"span": None, "span_state": "unmeasured",
            "reason": (f"за {limit} шагов по первым родителям не встретилось коммита, "
                       f"который на {ref} есть — история дерева чужая, размер работы "
                       f"НЕ ИЗМЕРЕН (пределом его называть нельзя)")}


def _count_span(repo: Path, span: str) -> Optional[int]:
    """`git rev-list --count <span>`. `None` — git не ответил (не ноль).

    Ноль здесь ЗНАЧАЩЕЕ значение («база и есть вершина `ref`»), поэтому склеить
    его с «не сосчитали» нельзя ни при каких условиях: ровно эта пара и
    различает свежую сироту от заброшенной ветки четырёхмесячной давности.
    """
    code, out = _git(repo, "rev-list", "--count", span)
    if code != 0:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def _tree_row(tree: Path, lineage: Path, ref: str, *, limit: int = SPAN_LIMIT) -> dict:
    code, sha = _git(tree, "rev-parse", "HEAD")
    if code != 0 or not sha:
        return {"tree": str(tree), "verdict": "no_head",
                "reason": f"git не назвал HEAD дерева: {sha or 'пусто'} (код {code})"}
    dcode, dout = _git(tree, "status", "--porcelain")
    dirty = len([x for x in dout.splitlines() if x.strip()]) if dcode == 0 else None
    row = {"tree": str(tree), "head": sha, "dirty": dirty}

    present = _present(lineage, sha)
    if present is None:
        return {**row, "verdict": "unmeasured",
                "reason": f"полный клон не ответил, есть ли у него {sha[:9]}"}
    if not present:
        row["verdict"] = "never_pushed"
        row["reason"] = (f"коммита {sha[:9]} нет в полном клоне {lineage} ВОВСЕ — "
                         f"он не уезжал ни под каким именем")
        row.update(measure_span(tree, lineage, sha, ref, limit=limit))
        return row

    anc = _is_ancestor(lineage, sha, ref)
    if anc is None:
        return {**row, "verdict": "unmeasured",
                "reason": f"полный клон не ответил, предок ли {sha[:9]} для {ref}"}
    row["verdict"] = "on_main" if anc else "off_main_branch"
    if not anc:
        row["reason"] = (f"коммит {sha[:9]} в полном клоне ЕСТЬ, но {ref} его не содержит — "
                         f"работа на невлитой ветке, это вопрос мержа, а не подъёма")
    return row


def sweep(repo_root: str | Path = _REPO_ROOT, *, ref: str = REF_DEFAULT,
          lineage_candidates: Sequence[str] = LINEAGE_CANDIDATES_DEFAULT,
          limit: int = SPAN_LIMIT,
          fresh_base_lag_max: int = FRESH_BASE_LAG_MAX) -> dict:
    """Перепись сирот. Возвращает замер; НИЧЕГО не правит и не поднимает."""
    repo = Path(repo_root)
    try:
        lineage, rejected = pick_lineage_repo(list(lineage_candidates))
    except Unmeasured as exc:
        return {"state": "unmeasured", "reason": str(exc), "ref": ref,
                "lineage_repo": None, "lineage_rejected": [], "rows": [], "tally": {}}
    try:
        trees = worktrees(repo)
    except Unmeasured as exc:
        return {"state": "unmeasured", "reason": str(exc), "ref": ref,
                "lineage_repo": str(lineage),
                "lineage_rejected": rejected, "rows": [], "tally": {}}

    rows = [_tree_row(t, lineage, ref, limit=limit) for t in trees]
    tally = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    unknown = [r["verdict"] for r in rows if r["verdict"] not in VERDICTS]
    if unknown:  # перечень VERDICTS замкнут — расхождение есть дефект прибора
        return {"state": "unmeasured",
                "reason": f"исход вне объявленного перечня: {sorted(set(unknown))}",
                "ref": ref, "lineage_repo": str(lineage),
                "lineage_rejected": rejected, "rows": rows, "tally": tally}
    assert sum(tally.values()) == len(rows), "учёт не сошёлся"
    candidates = [r for r in rows if r["verdict"] in CANDIDATE_VERDICTS]
    return {"state": "measured", "ref": ref, "lineage_repo": str(lineage),
            "lineage_rejected": rejected, "repo_root": str(repo),
            "trees": len(rows), "rows": rows, "tally": tally,
            "candidates": candidates,
            "fresh_base_lag_max": fresh_base_lag_max,
            "candidates_with_measured_span": [
                r for r in candidates if r.get("span_state") == "measured"],
            "fresh_candidates": [
                r for r in candidates
                if r.get("base_lag_state") == "measured"
                and r["base_lag"] <= fresh_base_lag_max],
            "span_limit": limit}


def report(doc: dict) -> list[str]:
    """Строки отчёта. Выбор клона ПЕЧАТАЕТСЯ — иначе читатель не узнает, о чьём `main` ответ."""
    if doc.get("state") == "unmeasured":
        return [f"⚠️ перепись сирот НЕ ИЗМЕРЕНА: {doc.get('reason')}"]
    lines = [f"перепись сирот: деревьев {doc['trees']}, ссылка {doc['ref']}",
             f"   родословную спрашивали у ПОЛНОГО клона: {doc['lineage_repo']}"]
    for r in doc.get("lineage_rejected", []):
        lines.append(f"   отвергнут клон {r['repo']}: {r.get('reason', r.get('state'))}")
    t = doc["tally"]
    lines.append("   исходы: " + " · ".join(f"{k} {t[k]}" for k in VERDICTS))
    measured = doc["candidates_with_measured_span"]
    fresh = doc["fresh_candidates"]
    lines.append(f"   кандидатов {len(doc['candidates'])}, из них пролёт ИЗМЕРЕН у "
                 f"{len(measured)}, база СВЕЖАЯ (отстаёт ≤ "
                 f"{doc['fresh_base_lag_max']}) у {len(fresh)}")
    for r in sorted(fresh, key=lambda x: x["span"]):
        lines.append(f"   🔶 ПОДНЯТЬ: {r['tree']} · {r['head'][:9]} · пролёт {r['span']} "
                     f"коммит(ов) · база отстаёт {r['base_lag']} · грязных файлов {r['dirty']}")
    for r in sorted(measured, key=lambda x: (x.get("base_lag") is None, x.get("base_lag") or 0)):
        if r in fresh:
            continue
        lag = (f"{r['base_lag']}" if r.get("base_lag_state") == "measured"
               else "НЕ ИЗМЕРЕНО")
        lines.append(f"   ▫️ не свежая: {r['tree']} · {r['head'][:9]} · пролёт {r['span']} · "
                     f"база отстаёт {lag}")
    for r in doc["candidates"]:
        if r.get("span_state") != "measured":
            lines.append(f"   ▫️ пролёт НЕ ИЗМЕРЕН: {r['tree']} · {r.get('reason', '')[:90]}")
    if not fresh:
        lines.append("   ✅ поднимать нечего: ни одного кандидата со свежей базой")
    return lines


def _stamp_now(now=None) -> str:
    import datetime as _dt
    moment = now or _dt.datetime.now(_dt.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(repo_root: str | Path = _REPO_ROOT, *, data_dir: Optional[Path] = None,
        dest: Optional[Path] = None, write: bool = True, now=None, **kw) -> dict:
    """Один замер + запись артефакта для шага 0-офис.

    Такта у этого замера НЕТ намеренно: он стои́т секунды, а заказ G911 п. 1
    предписывает его ПЕРВЫМ действием каждого цикла — гейт по сроку сделал бы
    «не мерили в этом цикле» неотличимым от «кандидатов нет».
    """
    root = Path(repo_root)
    source = Path(data_dir) if data_dir is not None else root / "data"
    target = Path(dest) if dest is not None else source / ARTIFACT
    doc = sweep(root, **kw)
    doc["invoked_by"] = call_provenance(tree_root=root)
    doc["generated_at"] = _stamp_now(now)
    if write:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(target))
    return {"measured": True, "doc": doc, "artifact": str(target)}


def format_report(doc: dict, max_rows: int = 5) -> list[str]:
    """Отрисовка для шага 0-офис. Правило отрисовки живёт У ПРОИЗВОДИТЕЛЯ —
    вторая копия у читателя разошлась бы с ним молча (ADR-220)."""
    head = ["— перепись СИРОТ: готовая работа предшественника вне `origin/main` (ADR-923) —"]
    return head + ["   " + line for line in report(doc)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Коды: 0 — поднимать нечего · 1 — кандидат НАЗВАН · 2 — НЕ ИЗМЕРЕНО."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=str(_REPO_ROOT),
                    help="клон, чьи деревья переписываются (умолчание — своё)")
    ap.add_argument("--ref", default=REF_DEFAULT)
    ap.add_argument("--lineage", action="append", default=None,
                    help="клон для вопросов о происхождении; можно несколько, "
                         "порядок — объявленный приоритет")
    ap.add_argument("--span-limit", type=int, default=SPAN_LIMIT)
    ap.add_argument("--fresh-base-lag-max", type=int, default=FRESH_BASE_LAG_MAX,
                    help="насколько база кандидата вправе отставать от вершины, "
                         "чтобы работа считалась свежей")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    doc = sweep(args.repo_root, ref=args.ref,
                lineage_candidates=args.lineage or LINEAGE_CANDIDATES_DEFAULT,
                limit=args.span_limit,
                fresh_base_lag_max=args.fresh_base_lag_max)
    doc["invoked_by"] = call_provenance(tree_root=Path(args.repo_root))
    doc["generated_at"] = _stamp_now()
    if not args.no_write:
        dest = (Path(args.out) if args.out
                else Path(args.repo_root) / "data" / ARTIFACT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_save(doc, str(dest))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("\n".join(report(doc)))
    if doc.get("state") != "measured":
        return 2
    return 1 if doc["fresh_candidates"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
