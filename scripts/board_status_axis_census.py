#!/usr/bin/env python3
"""Перепись ОСИ СТАТУСА производного индекса очереди (ADR-1062, заказ G1049 п. 2).

**Чей это долг.** ADR-1060 закрыл у доски `nimbalyst-local/tracker/_BOARD.md` ось 1 —
«уехала карточка, строки о ней на доске НЕТ ВОВСЕ». Ось 2 — «строка ЕСТЬ, но статус на
ней ДРУГОЙ» — тот ADR оставил НЕ ИЗМЕРЕННОЙ и назвал причину: статус доски
разрешается против `origin` ТОГО ДНЯ (`build_tracker_board.resolve_against_origin`), а
временный каталог не репозиторий. В замере 400 вершин ось затронула 23 вершины, и это
была ВЕРХНЯЯ ГРАНИЦА КАНДИДАТОВ, а не население.

**Что мерит этот прибор.** Для каждой вершины `origin/main`, которая тронула карточку
трекера: что говорит о статусе этой карточки доска ТОЙ ЖЕ вершины против того, что
говорит о себе САМА карточка той же вершины. Обе стороны — с origin, то есть
сравниваются две версии ОДНОГО состояния, а не дерево с чужим графом.

**Почему вопрос у ДОСТАВЛЯЕМОЙ карточки разрешим без угадывания** (премиса заказа,
которую прибор проверяет, а не принимает): `resolve_against_origin` переписывает статус
ТОЛЬКО у `stale` — карточки, чьё содержимое найдено в ИСТОРИИ origin для её же пути.
Байты, которые сессия СЕЙЧАС доставляет, становятся вершиной origin этим же пушем, то
есть по сроку они свежайшие по построению. Остаётся ровно один случай, где премиса не
держит: доставляемые байты ДОСЛОВНО совпали с прежней версией того же пути (возврат к
старому состоянию) — тогда сверка назвала бы карточку `stale`, и доска несла бы статус
origin законно. Этот случай прибор НЕ прячет: он отдельный исход `revert_shaped`.

**Три исхода различимы** (инв. #17): измерено · измерено и равно нулю · НЕ ИЗМЕРЕНО с
названной причиной. Код возврата: 0 — расхождений нет · 1 — население НЕПУСТО · 2 — НЕ
ИЗМЕРЕНО.

**Клон — ВХОД, и усечённый клон есть третий исход, а не ответ** (`.claude/rules/deployment.md`,
поправка #1031): прод-клон и КАЖДЫЙ его worktree усечены (252 коммита из 28 011), а
`git log --all -- <путь>` на усечённом графе возвращает пусто КОДОМ 0 и без единого
предупреждения. Ошибка пошла бы в опасную сторону — усечение РОЖДАЕТ находку, которой
нет. Выбор клона ПЕЧАТАЕТСЯ: молча подставить полное зеркало хуже ошибки, потому что
читатель не узнает, о чьём `main` ему ответили.

**Двери разбора — по одной на вопрос, и обе чужие** (то же правило, что у гейта
ADR-1060 п. 3): что доска утверждает — `build_tracker_board.board_status_map`; что
говорит карточка — `build_tracker_board.card_status`. Своя копия любой из двух означала
бы, что перепись считает согласием то, что сборка доски считает расхождением.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

#: Каталог очереди и её производный индекс — предмет переписи.
TRACKER_DIR = "nimbalyst-local/tracker"
BOARD_PATH = f"{TRACKER_DIR}/_BOARD.md"

#: Клоны в ОБЪЯВЛЕННОМ порядке предпочтения. Усечённый отвергается с причиной.
REPO_CANDIDATES = (
    "/Users/yuriikulieshov/Documents/SPA_mirror",
    "/Users/yuriikulieshov/Documents/SPA_Claude",
)

#: ЗАМЕР населения оси 2 — ОДИН адрес на весь проект, и живёт он у ПРИБОРА,
#: который его мерит. Гейт доставки (`push_to_github.enforce_delivery_board_row`)
#: читает эти числа ОТСЮДА, а не держит свою копию: число, перепечатанное рядом с
#: прибором, перестаёт быть замером и становится константой — ровно тот дефект,
#: за который проект уже платил («~3,3 % фактических» в шестнадцати местах при
#: треке 5,3 %, `.claude/rules/site-numbers.md`). Перемерить:
#:     python3 scripts/board_status_axis_census.py --limit 0
POPULATION = {
    "measured_at": "2026-11-19",
    "window": "вся история origin/main, тронувшая очередь",
    "vertices_scanned": 1925,
    "pairs_measured": 3797,
    "agree": 2764,
    "disagree": 287,
    "disagree_vertices": 141,
    "no_row": 654,
    "revert_shaped": 0,
    "unmeasured": 92,
    #: Из 287 — те, где доска числила работу за ВЛАДЕЛЬЦЕМ, а карточка уже
    #: объявляла ответ (`ingested`/`owner-done`/`done` против `needs-owner`).
    "claimed_for_owner": 110,
    #: СВЕЖЕСТЬ класса объявлена отдельно и НАМЕРЕННО: 287 — число ИСТОРИЧЕСКОЕ,
    #: и выдать его за текущую частоту значило бы завысить цену гейта. Класс не
    #: угас (последний случай — 15.11), но распределён неравномерно: в последних
    #: 100 вершинах 1, в 100…400 — 58, в 400…1000 — 97, старше 1000 — 131.
    "latest_finding_at": "2026-11-15",
    "latest_finding_vertex": "7b387eb73",
    "in_last_100_vertices": 1,
}

#: Исходы одной пары «вершина × карточка». Перечень ЗАКРЫТ: форма вне него есть
#: дефект разбора, а не новый род, и прибор обязан сказать это вслух.
OUTCOMES = (
    "agree",            # доска и карточка говорят одно
    "disagree",         # ось 2: строка есть, статус ДРУГОЙ  ← предмет переписи
    "no_row",           # ось 1 (ADR-1060): строки о карточке нет вовсе
    "revert_shaped",    # байты карточки = прежняя версия пути ⇒ судить нельзя
    "unmeasured",       # причина названа поимённо
)


class Unmeasured(Exception):
    """Предпосылка не обеспечена. Третий исход, а не ноль и не скип."""


def _git(repo: Path, *args: str) -> tuple[int, bytes]:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    return p.returncode, p.stdout


def _git_text(repo: Path, *args: str) -> tuple[int, str]:
    code, out = _git(repo, *args)
    return code, out.decode("utf-8", errors="replace").strip()


def history_completeness(repo: Path) -> dict:
    """Способен ли клон отвечать на вопрос об истории пути: три исхода.

    Отдельный вопрос, и задаётся он ДО сцен: код возврата рабочего прогона на
    «способен ли клон» не отвечает — дословный урок `pyflakes`
    (`.claude/rules/deployment.md`, § про `pid`).
    """
    code, out = _git_text(repo, "rev-parse", "--is-shallow-repository")
    if code != 0 or out not in ("true", "false"):
        return {"state": "unmeasured",
                "reason": (f"git не ответил, усечён ли клон {repo}: "
                           f"{out or 'пусто'} (код {code})")}
    rc_n, n = _git_text(repo, "rev-list", "--count", "HEAD")
    reachable = int(n) if rc_n == 0 and n.isdigit() else None
    if out == "true":
        return {"state": "shallow", "reachable": reachable,
                "reason": (f"клон {repo} УСЕЧЁН (shallow): от HEAD достижимо "
                           f"{reachable} коммит(ов). `git log -- <путь>` на таком "
                           f"графе отвечает ПУСТО кодом 0, то есть «истории нет» "
                           f"неотличимо от «её здесь нет» — усечение РОЖДАЕТ "
                           f"находку, которой нет")}
    return {"state": "complete", "reachable": reachable}


def pick_repo(candidates=REPO_CANDIDATES) -> tuple[Path, list[dict]]:
    """Первый ПОЛНЫЙ клон объявленного порядка + перечень отвергнутых с причинами.

    Выбор возвращается вызывающему, чтобы тот его НАПЕЧАТАЛ. Прибор, подставивший
    клон молча, отвечает про чужой `main` под видом своего.
    """
    rejected: list[dict] = []
    for cand in candidates:
        p = Path(cand)
        if not (p / ".git").exists():
            rejected.append({"repo": cand, "state": "absent",
                             "reason": f"{cand} не является клоном репозитория"})
            continue
        verdict = history_completeness(p)
        if verdict["state"] == "complete":
            return p, rejected
        rejected.append({"repo": cand, **verdict})
    raise Unmeasured(
        "ни один объявленный клон не способен отвечать об истории пути: "
        + " · ".join(f"{r['repo']}: {r.get('reason', r['state'])}"
                     for r in rejected))


def _parsers():
    """Обе двери разбора — из дерева ЗАПУЩЕННОГО прибора, своей копии нет ни одной.

    **Дерево разбора и клон истории — РАЗНЫЕ входы, и склеить их нельзя.** Первая
    редакция этого прибора ввозила двери из клона, у которого спрашивает историю, и
    честно отказала кодом 2: полное зеркало отстаёт от рабочего дерева, двери
    `card_status` там ещё нет. Отказ был ВЕРЕН, но вопрос — не тот: мерка обязана
    быть той, которую мы доставляем (правило ADR-1060 п. 3), а граф — тем, который
    способен ответить (поправка #1031). Спроси мерку у графа — и перепись судила бы
    доставляемый код ЧУЖОЙ, отстающей копией правила.
    """
    scripts = str(Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import build_tracker_board as btb
    except Exception as exc:  # noqa: BLE001
        raise Unmeasured(f"прибор разбора доски не ввезён из {scripts}: {exc}")
    for door in ("board_status_map", "card_status"):
        if not hasattr(btb, door):
            raise Unmeasured(
                f"у прибора разбора нет двери `{door}` — что доска утверждает о "
                f"статусе, спросить НЕЧЕМ (своей копии правила здесь нет "
                f"намеренно)")
    return btb


def measure(repo: Path, limit: int | None = None) -> dict:
    """Перепись: по вершине на карточку. Возвращает отчёт, ничего не чинит."""
    btb = _parsers()
    args = ["rev-list", "origin/main"]
    if limit:
        args.insert(1, f"-n{limit}")
    code, out = _git_text(repo, *args, "--", TRACKER_DIR)
    if code != 0:
        raise Unmeasured(f"перечень вершин не получен (код {code}): {out[:200]}")
    vertices = out.split()
    if not vertices:
        raise Unmeasured(
            f"ни одной вершины `origin/main`, тронувшей {TRACKER_DIR} — на "
            f"усечённом клоне это ПУСТО кодом 0, и нулём населения не считается")

    tally: Counter = Counter()
    findings: list[dict] = []
    vertices_with_cards = 0
    for sha in vertices:
        code, names_raw = _git_text(repo, "show", "--name-only",
                                    "--pretty=format:", sha, "--", TRACKER_DIR)
        if code != 0:
            tally["unmeasured"] += 1
            continue
        cards = [n.strip() for n in names_raw.splitlines()
                 if n.strip().endswith(".md") and n.strip() != BOARD_PATH]
        if not cards:
            continue
        vertices_with_cards += 1
        rc_b, board_raw = _git(repo, "show", f"{sha}:{BOARD_PATH}")
        if rc_b != 0:
            tally["unmeasured"] += len(cards)
            continue
        try:
            rows = btb.board_status_map(board_raw.decode("utf-8"))
        except UnicodeDecodeError:
            tally["unmeasured"] += len(cards)
            continue
        if not rows:
            # Ни одной строки в объявленной форме ⇒ неизвестно, какая строка
            # является строкой карточки. «Статус другой» здесь было бы
            # утверждением о замере, которого не было.
            tally["unmeasured"] += len(cards)
            continue
        for rel in cards:
            base = os.path.basename(rel)
            rc_c, card_raw = _git(repo, "show", f"{sha}:{rel}")
            if rc_c != 0 or not card_raw:
                tally["unmeasured"] += 1   # карточка удалена этой вершиной
                continue
            try:
                said_by_card = btb.card_status(card_raw.decode("utf-8"))
            except UnicodeDecodeError:
                tally["unmeasured"] += 1
                continue
            if said_by_card is None:
                tally["unmeasured"] += 1   # поля `status:` нет вовсе
                continue
            said_by_board = rows.get(base)
            if said_by_board is None:
                tally["no_row"] += 1
                continue
            if said_by_board.strip() == said_by_card:
                tally["agree"] += 1
                continue
            # Расхождение ЕСТЬ. Прежде чем назвать его находкой — спросить, не
            # возврат ли это: байты карточки, дословно равные ПРЕЖНЕЙ версии того
            # же пути, сверка назвала бы `stale`, и доска несла бы статус origin
            # ЗАКОННО. Это НЕ находка, и прятать её в находки нельзя.
            if _looks_like_revert(repo, sha, rel, card_raw):
                tally["revert_shaped"] += 1
                continue
            tally["disagree"] += 1
            findings.append({"vertex": sha, "card": base,
                             "card_says": said_by_card,
                             "board_says": said_by_board.strip(),
                             "board_rows": len(rows)})

    measured = sum(tally[k] for k in OUTCOMES)
    return {
        "repo": str(repo),
        "vertices_scanned": len(vertices),
        "vertices_with_cards": vertices_with_cards,
        "pairs_measured": measured,
        "tally": {k: tally[k] for k in OUTCOMES},
        "findings": findings,
    }


def _looks_like_revert(repo: Path, sha: str, rel: str, card_raw: bytes) -> bool:
    """Равны ли байты карточки ДОСЛОВНО какой-то ПРЕЖНЕЙ версии того же пути.

    Ровно тот признак, по которому `check_tracker_drift` называет карточку
    `stale`, — и единственное состояние, в котором доска несёт статус origin
    законно. Спрашиваем по blob-ам ИСТОРИИ ПУТИ, а не «похоже старее»: «похоже»
    признаком не является.
    """
    code, out = _git_text(repo, "rev-list", f"{sha}^", "--", rel)
    if code != 0 or not out:
        return False
    # Хеш считаем БЕЗ `-w`: запись в объектную базу ЧУЖОГО клона есть правка
    # того, у кого мы лишь спрашиваем. Прибор только ЧИТАЕТ.
    p = subprocess.run(["git", "-C", str(repo), "hash-object", "--stdin"],
                       input=card_raw, capture_output=True)
    if p.returncode != 0:
        return False
    mine = p.stdout.decode().strip()
    for prev in out.split():
        rc, blob = _git_text(repo, "rev-parse", f"{prev}:{rel}")
        if rc == 0 and blob == mine:
            return True
    return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=("Перепись оси СТАТУСА производного индекса очереди: что "
                     "доска утверждает против того, что говорит карточка."))
    ap.add_argument("--repo-root", default=None,
                    help=("клон, у которого спрашивать историю. Умолчание — "
                          "первый ПОЛНЫЙ из объявленного порядка; выбор "
                          "ПЕЧАТАЕТСЯ всегда"))
    ap.add_argument("--limit", type=int, default=400,
                    help="сколько вершин смотреть (0 — все)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        if args.repo_root:
            repo = Path(args.repo_root)
            verdict = history_completeness(repo)
            if verdict["state"] != "complete":
                raise Unmeasured(
                    f"названный клон отвечать не способен — "
                    f"{verdict.get('reason', verdict['state'])}")
            rejected = []
        else:
            repo, rejected = pick_repo()
        report = measure(repo, args.limit or None)
    except Unmeasured as exc:
        if args.json:
            print(json.dumps({"state": "unmeasured", "reason": str(exc)},
                             ensure_ascii=False, indent=2))
        else:
            print(f"⚠️  НЕ ИЗМЕРЕНО: {exc}")
        return 2

    report["rejected_repos"] = rejected
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if report["tally"]["disagree"] else 0

    t = report["tally"]
    print(f"клон: {report['repo']}"
          + (f"  (отвергнуто: "
             + "; ".join(f"{r['repo']} — {r['state']}" for r in rejected) + ")"
             if rejected else "  (объявленный порядок, первый же полон)"))
    print(f"вершин просмотрено: {report['vertices_scanned']} · из них тронули "
          f"карточку: {report['vertices_with_cards']} · пар измерено: "
          f"{report['pairs_measured']}")
    print(f"  согласие                : {t['agree']}")
    print(f"  ОСЬ 2 · СТАТУС ДРУГОЙ   : {t['disagree']}")
    print(f"  ось 1 · строки нет      : {t['no_row']}  (предмет ADR-1060)")
    print(f"  возврат к прежним байтам: {t['revert_shaped']}  (судить нельзя — "
          f"доска несёт статус origin законно)")
    print(f"  НЕ ИЗМЕРЕНО             : {t['unmeasured']}")
    if report["findings"]:
        print(f"\nнаселение оси 2 НЕПУСТО — {t['disagree']}:")
        for f in report["findings"][:30]:
            print(f"  {f['vertex'][:9]}  {f['card']}: карточка `{f['card_says']}`"
                  f" ← доска говорит `{f['board_says']}`")
        if len(report["findings"]) > 30:
            print(f"  … и ещё {len(report['findings']) - 30} "
                  f"(полный перечень — `--json`)")
        return 1
    print("\n✅ расхождений оси 2 в этом окне НЕТ — и это ИЗМЕРЕННЫЙ ноль")
    return 0


if __name__ == "__main__":
    sys.exit(main())
