#!/usr/bin/env python3
"""ЛИЧНОСТЬ репозитория, в который ведёт доказанный `cd` (ЗАКАЗ #579).

ADR-355 доказал, что `cd` **исполняется**. ADR-356 доказал, что каталог,
в который он ведёт, есть **КОРЕНЬ** рабочей копии — и на этом остановился,
приняв на веру то, чего не мерил: что это корень **ТОГО САМОГО** репозитория.
«Корень» и «тот репозиторий» — разные утверждения, и первое молча выдавалось
за второе ровно так же, как до ADR-356 «каталог задан» выдавалось за «каталог
тот самый».

Вопрос заказа дословно: **чем доказывается личность репозитория, в который
ведёт `cd`, и у скольких зовов с доказанным корнем она доказана?**

## Что здесь объявлено ЛИЧНОСТЬЮ — и почему остальное ею не является

Заказ потребовал сказать ЗАРАНЕЕ, какое свойство есть личность, а какое лишь
совпадает с ней на нашем хосте. Отвечаем, и каждый отвод — ЗАМЕР, а не мнение.

**ЛИЧНОСТЬ = ПЕРЕСЕЧЕНИЕ ИСТОРИЙ.** Две рабочие копии суть один репозиторий
тогда и только тогда, когда они делят хотя бы один коммит. Свойство
внутреннее (живёт в объектах, не в конфиге), неподделываемое одной командой,
переживает неполный клон и переживает отсутствие `origin` вовсе.
Доказательство — `merge-base --is-ancestor <якорь одного> HEAD` в другом, в
любую из двух сторон; при неполной истории прямое направление может быть
недоступно, обратное при этом работает, и прибор называет, каким именно
направлением доказал.

**НЕ личность №1 — `remote get-url origin`.** Это КОНФИГ: `git remote set-url`
меняет его, не трогая репозиторий, а копия без `origin` остаётся тем же
репозиторием. На нашем хосте он к тому же врёт в обе стороны сразу: прод-дерево
несёт `…/SPA.git`, зеркало — `…/SPA` (тот же репозиторий, два написания, и
строковое равенство их не признает), а любой чужой клон можно настроить на наш
URL, ничего общего с нашей историей не имея. Наблюдение ДОКЛАДЫВАЕТСЯ отдельной
строкой как подтверждающее и НИКОГДА не входит в вердикт.

**НЕ личность №2 — корневой коммит (`rev-list --max-parents=0 HEAD`).** Он
ВЫГЛЯДИТ внутренним, а на деле есть функция ГЛУБИНЫ ЛОКАЛЬНОГО КЛОНА, и на этой
самой машине он изготовил бы ложную находку. Замер 2026-09-12:

| дерево | коммитов | `--max-parents=0` | `--is-shallow-repository` |
|---|---|---|---|
| `~/Documents/SPA_Claude` (прод) | 443 | `b9cf63fb` | **true** |
| `~/Documents/SPA_mirror` | 26 829 | `35b0e8e1` | false |

Прод-дерево НЕПОЛНОЕ, и `--max-parents=0` отдаёт там не корень, а **границу
обрезки**, которая выглядит корнем и ничем от него не отличается. Наивная сверка
«корневой коммит» объявила бы прод-дерево и зеркало РАЗНЫМИ репозиториями —
уверенная ложная находка того самого класса, против которого написана вся цепь
(«не измерено, выданное за ответ», `.claude/rules/deployment.md`). Поэтому
`--max-parents=0` используется только как **якорь** — самый старый ВИДИМЫЙ
коммит, — а вердикт выносится по пересечению, которое обрезку переживает:
`b9cf63fb` присутствует в зеркале и является там предком HEAD ⇒ пересечение
доказано, личность одна.

**НЕ личность №3 — ПУТЬ.** `rev-parse --show-toplevel` одинаково честно назовёт
корнем `/tmp/spa_cNNN`, `~/Documents/SPA_mirror` и `~/Documents/earn-defi`. Это
КОРНИ, но первое — та же история на ДРУГОЙ ревизии, второе — та же история,
отстающая по построению, третье — совсем другой репозиторий, и
`checkout origin/main -- spa_core` там означает третье.

**НЕ личность №4, и это отдельная ловушка — «та же история» ≠ «та же ревизия».**
Признак связанной рабочей копии (`--git-common-dir` ≠ `--git-dir`) и сам HEAD
ДОКЛАДЫВАЮТСЯ, но в вердикт не идут: `/tmp/spa_cNNN` есть та же личность и
именно поэтому опасен — `reset --hard` там разрушает не чужое, а своё, на чужой
ревизии. Личность отвечает на вопрос «тот ли это репозиторий», а не «та ли это
ревизия»; второй вопрос тут НЕ решается и не выдаётся за решённый.

## Три исхода, и третий не складывается в первый (инвариант #17)

| исход | что доказано |
|---|---|
| `same_identity` | истории доказанно пересекаются — это тот же репозиторий |
| `other_identity` | пересечения доказанно нет, либо каталог не рабочая копия |
| `undetermined` | прибор не знает и не выдумывает |

У зова, чей каталог пришёл из ОКРУЖЕНИЯ, личность не определена **по
построению** — каталога ещё нет, судить не о чем, — и это `undetermined`,
а не «та же».

## Основание доказательства ПУТЕШЕСТВУЕТ или нет — это и есть ответ заказа

Счёт «у скольких доказана» без этого различения был бы верным ответом не на тот
вопрос. У доказанной личности РАЗНАЯ цена:

- **`by_construction`** — зов идёт за СВОЕЙ копией (ADR-356: каталог есть корень
  того дерева, где лежит исполняемый файл). Личность тогда есть свойство КОДА:
  куда копию ни положи, `cd` приведёт в репозиторий, которому копия принадлежит.
  В чужой репозиторий такой зов не попадёт НИКОГДА, на любой машине.
- **`by_construction_hijackable`** — зов тоже идёт за своей копией, но МЕСТО
  копии выводится из имени, которое bash ставит сам (`BASH_SOURCE`). Экспорт
  этого имени ПЕРЕБИВАЕТ его на bash 3.2.57 (macOS, `/bin/bash` прод-хоста) и
  не перебивает на bash 5.x. ADR-356 вынес эту пробу из своего вердикта как
  свойство хоста — и для вопроса «корень ли» был прав. Для вопроса «ТОТ ЛИ
  репозиторий» она решает: перехваченный `BASH_SOURCE` уводит зов в дерево,
  выбранное ПОЗВАВШИМ. Замер 12.09: три зова `secure_git_push.sh`, и следом за
  ними идёт `git push`. Основание расщеплено, а не усреднено.
- **`by_host`** — каталог ПРИКОЛОЧЕН литералом. На этой машине по литералу лежит
  наш репозиторий — значит, личность доказана, и это честный факт. Но доказана
  она ФАЙЛОВОЙ СИСТЕМОЙ ЭТОЙ МАШИНЫ, а не кодом: доказательство не
  путешествует. Под другим `$HOME`, на другом хосте, при переносе дерева по
  тому же пути может оказаться что угодно либо ничего.

Предметом класса (код 3) объявлены **`by_host` + `by_construction_hijackable` +
`other_identity`** — то, чья личность кодом не гарантирована. `undetermined` докладывается, но в предмет
ЭТОГО прибора не входит: это ровно населённый предмет ADR-356 (значение задаёт
окружение), и считать его дважды значило бы изобразить рост класса там, где
класс один.

Коды возврата (ADR-347): 0 — предмет пуст · 3 — предмет непуст · 2 — НЕ
ИЗМЕРЕНО с названной причиной. 1 оставлен CPython, чтобы падение прибора
никогда не выглядело его находкой.
"""
from __future__ import annotations

import sys
import json
import argparse
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shell_git_cd_target_census import census                # noqa: E402

TIMEOUT = 60


def _git(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, timeout=TIMEOUT)


# ─────────────────────────── наблюдение о дереве ───────────────────────────

def repo_facts(path: str) -> tuple[dict | None, str | None]:
    """Наблюдения о каталоге. Возвращает (факты, причина-почему-не-измерено).

    Каталога нет на ЭТОЙ машине — это НЕ «другой репозиторий»: скрипт может
    исполняться там, где он есть. Третий исход, а не приговор."""
    p = Path(path)
    if not p.is_dir():
        return None, f"каталога {path!r} нет на этой машине"
    top = _git(["rev-parse", "--show-toplevel"], cwd=str(p))
    if top.returncode != 0:
        return {"is_repo": False, "path": str(p)}, None

    def one(args, default=""):
        r = _git(args, cwd=str(p))
        return r.stdout.strip() if r.returncode == 0 else default

    anchors = [s for s in one(["rev-list", "--max-parents=0", "HEAD"]).split() if s]
    gd, cd_ = one(["rev-parse", "--git-dir"]), one(["rev-parse", "--git-common-dir"])
    return {
        "is_repo": True,
        "path": str(p),
        "toplevel": str(Path(top.stdout.strip()).resolve()),
        "anchors": anchors,
        "head": one(["rev-parse", "HEAD"]),
        "shallow": one(["rev-parse", "--is-shallow-repository"]) == "true",
        "origin": one(["remote", "get-url", "origin"], default=""),
        "linked_worktree": bool(gd and cd_ and
                                Path(gd).resolve() != Path(cd_).resolve()),
    }, None


def _has_commit(facts: dict, sha: str) -> bool:
    r = _git(["cat-file", "-t", sha], cwd=facts["path"])
    return r.returncode == 0 and r.stdout.strip() == "commit"


def _is_ancestor(facts: dict, sha: str) -> bool:
    return _git(["merge-base", "--is-ancestor", sha, "HEAD"],
                cwd=facts["path"]).returncode == 0


def histories_intersect(a: dict, b: dict) -> tuple[bool | None, str]:
    """Делят ли две рабочие копии хоть один коммит.

    Доказывается в ЛЮБУЮ из двух сторон: при неполной истории прямое
    направление недоступно, обратное работает. Возвращает (да/нет/None, чем)."""
    # Якорь нужен С ОБЕИХ сторон. Сторона без единого видимого коммита
    # (пустой репозиторий, HEAD в никуда) НЕ «не пересекается» — о ней просто
    # нечего спросить, и объявить её «доказанно другой» значило бы изготовить
    # ложную находку. Третий исход, и он не складывается ни в первый, ни во
    # второй (инвариант #17).
    missing = [name for name, side in (("цели", a), ("опорного дерева", b))
               if not side.get("anchors")]
    if missing:
        return None, ("нет видимого якоря истории у " + " и у ".join(missing)
                      + " (пустой репозиторий или HEAD без коммитов) — "
                      "пересечение не доказуемо ни в одну сторону")
    for src, dst, name in ((a, b, "цели"), (b, a, "опорного дерева")):
        for sha in src.get("anchors", []):
            if _is_ancestor(dst, sha):
                return True, (f"якорь {name} {sha[:12]} — предок HEAD "
                              f"в {dst['path']!r} (предковость)")
    for src, dst, name in ((a, b, "цели"), (b, a, "опорного дерева")):
        for sha in src.get("anchors", []):
            if _has_commit(dst, sha):
                return True, (f"якорь {name} {sha[:12]} присутствует объектом "
                              f"в {dst['path']!r} (наличие объекта; предковость "
                              "недоступна — история обрезана)")
    return False, (f"ни один якорь ({', '.join(s[:12] for s in a.get('anchors', []) + b.get('anchors', []))}) "
                   "не найден в противоположном дереве — истории не пересекаются")


def identity_of(target: str, reference: dict) -> tuple[str, dict]:
    """Личность репозитория по пути `target` относительно опорного дерева."""
    facts, why = repo_facts(target)
    if facts is None:
        return "undetermined", {"why": why}
    if not facts["is_repo"]:
        return "other_identity", {
            "why": f"{target!r} существует, но рабочей копией git не является"}
    same, basis = histories_intersect(facts, reference)
    if same is None:
        return "undetermined", {"why": basis}
    detail = {
        "why": basis,
        "origin": facts["origin"],
        "origin_matches_reference": facts["origin"] == reference.get("origin"),
        "same_revision": facts["head"] == reference.get("head"),
        "linked_worktree": facts["linked_worktree"],
        "shallow": facts["shallow"],
        "anchors": facts["anchors"],
    }
    return ("same_identity" if same else "other_identity"), detail


# ─────────────────────────────── перепись ───────────────────────────────

def identity_census(repo_root: Path) -> dict:
    repo_root = repo_root.resolve()
    reference, why = repo_facts(str(repo_root))
    if reference is None or not reference.get("is_repo"):
        return {"unmeasured_fatal": (
            f"--root {str(repo_root)!r} не рабочая копия git: "
            f"{why or 'корень не разрешился'} — вопрос о личности без опорной "
            "личности не имеет смысла")}

    base = census(repo_root)
    if "unmeasured_fatal" in base:
        return base

    rows, cache = [], {}
    for r in base["rows"]:
        if r["verdict"] == "unmeasured":
            rows.append({**r, "identity": "undetermined", "basis": "n/a",
                         "identity_detail": {
                             "why": "каталог зова не измерен (ADR-356) — "
                                    "личность без каталога не определена"}})
            continue
        if r["verdict"] == "undetermined":
            rows.append({**r, "identity": "undetermined", "basis": "n/a",
                         "identity_detail": {
                             "why": "каталог задаёт ОКРУЖЕНИЕ (ADR-356): "
                                    "личность не определена ПО ПОСТРОЕНИЮ"}})
            continue

        det = r.get("detail") or {}
        pinned, value = det.get("pinned"), det.get("value")
        if pinned and not isinstance(value, str):
            # Приколочено, но значения нет — судить не о чем. Третий исход
            # с названной причиной, а не догадка о «том же» репозитории.
            rows.append({**r, "identity": "undetermined", "basis": "n/a",
                         "identity_detail": {
                             "why": "каталог объявлен приколоченным, но его "
                                    f"значение не строка ({value!r}) — "
                                    "личность не определена"}})
            continue
        if not pinned:
            # Зов идёт за своей копией. ADR-356 доказал, что каталог есть
            # корень ТОГО дерева, где лежит исполняемый файл; репозиторий
            # этого дерева и есть репозиторий, которому копия принадлежит.
            #
            # НО «гарантирована кодом» верно лишь против НЕВРАЖДЕБНОГО
            # окружения. Если место копии выводится из имени, которое bash
            # ставит сам (`BASH_SOURCE`), экспорт этого имени перебивает его
            # на bash 3.2.57 (macOS, `/bin/bash` прод-хоста) и не перебивает
            # на bash 5.x. ADR-356 вынес эту пробу из своего вердикта как
            # свойство хоста — и был прав для вопроса «корень ли». Для вопроса
            # «ТОТ ЛИ репозиторий» она решает: перехваченный `BASH_SOURCE`
            # уводит зов в дерево, выбранное позвавшим. Поэтому основание
            # РАСЩЕПЛЕНО, а не усреднено.
            hijack = (det.get("hijack") or {})
            if hijack.get("taken"):
                rows.append({**r, "identity": "same_identity",
                             "basis": "by_construction_hijackable",
                             "identity_detail": {
                                 "why": ("зов идёт за своей копией, но место копии "
                                         f"выводится из {', '.join(hijack.get('names', []))}, "
                                         f"а на этом хосте ({hijack.get('bash', '?')}) "
                                         "экспорт этого имени его ПЕРЕБИВАЕТ — личность "
                                         "гарантирована кодом только против невраждебного "
                                         "окружения"),
                                 "hijack": hijack}})
                continue
            rows.append({**r, "identity": "same_identity",
                         "basis": "by_construction",
                         "identity_detail": {
                             "why": "зов идёт за СВОЕЙ копией: каталог есть "
                                    "корень дерева, где лежит исполняемый файл "
                                    "(ADR-356) — личность гарантирована кодом, "
                                    "доказательство путешествует с копией"}})
            continue

        target = str(value)
        if target not in cache:
            cache[target] = identity_of(target, reference)
        verdict, detail = cache[target]
        rows.append({**r, "identity": verdict,
                     "basis": "by_host" if verdict == "same_identity" else "n/a",
                     "identity_detail": {**detail, "target": target}})

    return {"root": str(repo_root), "reference": reference,
            "rows": rows, "unread": base.get("unread", [])}


ABSENT_MARK = "нет на этой машине"


def unmeasurable_here(rows) -> list[str]:
    """Приколоченные цели, которых на ЭТОМ хосте нет.

    Предмет прибора (`by_host`) измерим только там, где приколоченные пути
    существуют. На хосте, где их нет, каждая такая цель честно становится
    `undetermined`, предмет ВЫГЛЯДИТ пустым — и храповик, сверенный с базой,
    посоветовал бы её сократить. Это ровно «не измерено», выданное за «чисто»
    (и хуже: за УЛУЧШЕНИЕ). Поэтому такой хост обязан отказать вслух, а не
    зеленеть: замер `by_host` есть свойство машины, и машина обязана быть той."""
    return sorted({f"{r['file']}:{r['line']}" for r in rows
                   if r["identity"] == "undetermined"
                   and ABSENT_MARK in (r["identity_detail"] or {}).get("why", "")})


def subject_keys(rows) -> list[str]:
    """Предмет ЭТОГО прибора: личность кодом не гарантирована.

    `undetermined` сюда НЕ входит — это населённый предмет ADR-356, и считать
    его дважды значило бы изобразить рост класса там, где класс один."""
    return sorted({f"{r['file']}:{r['line']}" for r in rows
                   if r["identity"] == "other_identity"
                   or (r["identity"] == "same_identity"
                       and r["basis"] in ("by_host",
                                          "by_construction_hijackable"))})


# ──────────────────────────────── отчёт ────────────────────────────────

ORDER = ["same_identity", "other_identity", "undetermined"]
TITLE = {"same_identity": "ТА ЖЕ ЛИЧНОСТЬ (истории пересекаются)",
         "other_identity": "доказанно ДРУГАЯ личность",
         "undetermined": "НЕ ОПРЕДЕЛЕНО"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--baseline", default=None,
                    help="храповик: файл с замороженным предметом")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    rep = identity_census(root)

    if "unmeasured_fatal" in rep:
        msg = f"⛔ НЕ ИЗМЕРЕНО: {rep['unmeasured_fatal']}"
        print(json.dumps({"unmeasured": rep["unmeasured_fatal"]},
                         ensure_ascii=False) if args.json else msg)
        return 2

    rows = rep["rows"]
    subject = subject_keys(rows)
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["identity"], []).append(r)
    by_basis = {b: sum(1 for r in rows if r["basis"] == b)
                for b in ("by_construction", "by_construction_hijackable",
                          "by_host")}

    frozen, ratchet_err = None, None
    if args.baseline:
        bp = Path(args.baseline)
        if not bp.is_file():
            ratchet_err = f"базы храповика нет: {args.baseline!r}"
        else:
            try:
                frozen = sorted(set(json.loads(bp.read_text("utf-8"))["subject"]))
            except Exception as exc:                      # noqa: BLE001
                ratchet_err = f"база храповика не разобрана ({exc})"

    # `--json` печатает РОВНО один документ и ничего больше. Человеческие
    # строки вердикта и храповика идут в stderr: потребитель разбирает stdout,
    # и «документ, а следом фраза» давится на разборе. Дефект найден у прибора
    # ADR-356 и воспроизведён здесь дословно — поэтому закреплён тестом.
    def say(msg):
        print(msg, file=sys.stderr if args.json else sys.stdout)

    if args.json:
        print(json.dumps({
            "root": rep["root"], "calls": len(rows),
            "by_identity": {k: len(groups.get(k, [])) for k in ORDER},
            "by_basis": by_basis, "subject": subject,
            "unread": rep["unread"],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"ЛИЧНОСТЬ репозитория, куда ведёт `cd` — мерено из {rep['root']!r}")
        print(f"  опорная личность: origin={rep['reference']['origin'] or '—'} · "
              f"якорь={(rep['reference']['anchors'] or ['—'])[0][:12]} · "
              f"неполный клон={'да' if rep['reference']['shallow'] else 'нет'}")
        print(f"  зовов всего: {len(rows)}\n")
        for key in ORDER:
            grp = groups.get(key, [])
            print(f"── {TITLE[key]}: {len(grp)}")
            for r in grp:
                print(f"   {r['file']}:{r['line']}  [{r['basis']}]  "
                      f"{r['identity_detail'].get('why', '')[:120]}")
            print()
        print(f"основание доказанной личности: by_construction="
              f"{by_basis['by_construction']} (путешествует) · "
              f"by_construction_hijackable="
              f"{by_basis['by_construction_hijackable']} (следует за копией, но "
              f"МЕСТО копии перебивается экспортом) · "
              f"by_host={by_basis['by_host']} (доказано файловой системой "
              f"ЭТОЙ машины, не кодом)")

    if rep["unread"]:
        say(f"⛔ НЕ ИЗМЕРЕНО: {len(rep['unread'])} файл(ов) не прочитаны — "
            f"{rep['unread'][0]}")
        return 2
    if ratchet_err:
        say(f"\n⛔ НЕ ИЗМЕРЕНО: {ratchet_err} — «нет базы» не есть «чисто»")
        return 2

    # Отказ НЕ зависит от того, дали ли базу. Без базы пустой предмет напечатал
    # бы «✅ предмет пуст» — то же «не измерено», выданное за «чисто», только
    # без храповика. Вопрос «та ли это машина» задаётся ОТДЕЛЬНО и раньше.
    absent = unmeasurable_here(rows)
    if absent:
        say(f"\n⛔ НЕ ИЗМЕРЕНО: {len(absent)} приколоченных целей нет на этом "
            f"хосте ({', '.join(absent[:3])}…) — предмет `by_host` здесь "
            "невычислим, и пустой предмет НЕ означает, что класс сократился. "
            + ("База не сверяется: сокращать её по этому прогону запрещено."
               if frozen is not None else
               "Вердикт о предмете не выносится вовсе."))
        return 2

    if frozen is not None:
        new = [k for k in subject if k not in frozen]
        if new:
            say(f"\n🔴 ХРАПОВИК: предмет ВЫРОС на {len(new)} — "
                  + ", ".join(new))
            return 3
        gone = [k for k in frozen if k not in subject]
        if gone:
            say(f"\n🟢 предмет сократился на {len(gone)}: "
                  + ", ".join(gone) + " — обнови базу")
        say("\n✅ храповик: предмет не вырос")
        return 0

    if subject:
        say(f"\n🔴 ПРЕДМЕТ НЕПУСТ: {len(subject)} зов(ов), чья личность не "
              "гарантирована кодом")
        return 3
    say("\n✅ предмет пуст")
    return 0


if __name__ == "__main__":
    sys.exit(main())
