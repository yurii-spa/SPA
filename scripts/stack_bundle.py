#!/usr/bin/env python3
"""scripts/stack_bundle.py — ВТОРАЯ копия работы, которой нельзя уехать на origin.

**Зачем.** Доставка на origin держится на ОДНОМ ключе (`GITHUB_PAT_SPA`, Связка ключей).
24.11.2026 он истёк, и за сутки циклы #1238…#1248 сложили **стек из одиннадцати коммитов**
(ADR-1093…ADR-1103), которые физически некуда отдать. Замер 25.11 (цикл #1249):

* коммитов, достижимых от локального рефа и НЕ достижимых ни от одного `refs/remotes/origin/*`
  — **1345**, из них у семьи `rescue/*` ровно **11** (вложенные: `c1248` содержит все);
* вершина стека `92845a4fc` в полном зеркале `~/Documents/SPA_mirror` — **ОТСУТСТВУЕТ**
  (`git cat-file -e` ⇒ ненулевой код);
* то есть одиннадцать циклов работы жили в ОДНОМ объектном складе —
  `~/Documents/SPA_Claude/.git`, и повторно отдать их origin нельзя: ключ мёртв.

Рядом уже стоя́т два сторожа, и ни один не отвечает на нужный вопрос:

| Вопрос | Кто отвечает | Чего НЕ делает |
|---|---|---|
| объявил владение — доставил ли на origin? | `scripts/check_undelivered_work.py` | НАЗЫВАЕТ сироту, но её не СОХРАНЯЕТ |
| цел ли живой трек и `data/`? | `scripts/daily_backup.py` | возит `data/*.json` + `track.db`; git-объектов и ветвей не трогает ВОВСЕ |
| **есть ли у неотправленной работы ВТОРАЯ копия?** | этот модуль | всё остальное |

**Что делает.** Детерминированно, read-only для репозитория, только stdlib, **БЕЗ СЕТИ** —
то есть работает ровно в том состоянии, когда доставка закрыта:

1. спрашивает, что локально есть и на удалённом не лежит: все `refs/heads/*` МИНУС всё,
   достижимое от любого `refs/remotes/origin/*`;
2. пишет `git bundle` ВНЕ клона (атомарно: временный файл в том же каталоге + `os.replace`);
3. **проверяет его в ЧУЖОМ репозитории** и только после этого зовёт резервом.

## Почему bundle, а не второй клон и не ветка в зеркале

Напрашивающееся «довезти стек в полное зеркало» — ОШИБКА, и она того же класса, против
которого написано `.claude/rules/deployment.md` § поправка #1031: приборы выбирают зеркало,
чтобы отвечать на вопросы ИСТОРИИ («был ли этот файл на `main`?», «кто содержит этот
коммит?»). Локальная ветка, подложенная в зеркало, молча меняет ответы `log --all` и
`--contains` — находка оказывается выдумана графом, а не найдена в мире. **Bundle инертен:**
по нему не ходит ни один прибор, он не является рефом и в обход никого не попадает.

## Почему тонкий (range) bundle, а не самодостаточный

Предпосылки тонкого bundle лежат на origin, а репозиторий **ПУБЛИЧНЫЙ**: замер 25.11 —
анонимный `GET /repos/yurii-spa/SPA/...` отвечает **200**, тогда как тот же запрос с мёртвым
ключом даёт **401** (ADR-1095). То есть восстановление НЕ зависит от того, что сломано.
Самодостаточный bundle стоил бы полной истории (замер: 22 МБ тонкого против клона) и всё
равно требовал бы диска.

## Три исхода различимы кодом возврата (инв. #17)

* **0** — bundle записан **И ПРОВЕРЕН в чужом репозитории**;
* **1** — сохранять нечего: каждый локальный реф достижим от origin (**измеренный ноль**,
  а не «не смотрели»);
* **2** — **НЕ ИЗМЕРЕНО** с названной причиной: git не ответил · предпосылок нет в
  контрольном репозитории · проверка не прошла · каталог назначения не пишется.

**Непроверенный bundle резервом НЕ зовётся** (fail-CLOSED). Файл при этом остаётся на диске
и его путь ПЕЧАТАЕТСЯ — «у меня есть bundle, но проверить его нечем» обязано отличаться и от
«резерв есть», и от «резерва нет».

## Проверка обязана идти в ЧУЖОМ репозитории, иначе это тавтология

`git bundle verify`, выполненный в клоне-ИСТОЧНИКЕ, успешен ВСЕГДА: все предпосылки у него
по построению на месте. Такой зелёный ответ — ответ на СВОЙ вопрос, а не на нужный
(`.claude/rules/site-numbers.md`: «Зелёный ответ сторожа на СВОЙ вопрос никогда не есть ответ
на нужный»). Поэтому проверка идёт в репозитории, у которого спорных коммитов НЕТ, а
предпосылки ЕСТЬ — по умолчанию полное зеркало.

## Чего это НЕ закрывает

Обе копии живут на ОДНОМ диске: гибель машины уносит и клон, и bundle. Закрыт реальный
наблюдённый класс — порча клона, удаление ветви, `git gc`, уборка «одноразового» дерева,
которое оказалось боевым (`.claude/rules/deployment.md`, п. 4). Вынос bundle на внешний
носитель или в чужое хранилище — ОТДЕЛЬНОЕ решение (публикация вовне есть предмет №3
границы ADR-285), а не умолчание этого модуля. И bundle не делает работу доставленной:
`check_undelivered_work.py` по-прежнему обязан называть её сиротой, пока она не на origin.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

# Исходы. Имена — часть вердикта: «nothing» это ИЗМЕРЕННЫЙ ноль, а «unmeasured» — его
# отсутствие, и подставлять одно вместо другого запрещено (инв. #17).
BUNDLED, NOTHING, UNMEASURED = "bundled", "nothing", "unmeasured"
# Состояние ЗАМЕРА (не исход прогона): есть ли вообще что сохранять.
HAVE_WORK = "have_work"
VERIFIED, UNVERIFIED = "verified", "unverified"

ORIGIN_PREFIX = "refs/remotes/origin/"
HEADS_PREFIX = "refs/heads/"

DEFAULT_ROOT = pathlib.Path.home() / "Documents" / "SPA_Claude"
# ВНЕ клона намеренно: резерв, лежащий внутри того, что он страхует, страхует только от
# `git`, но не от потери каталога.
DEFAULT_DEST = pathlib.Path.home() / "Documents" / "SPA_stack_bundles"
# Контроль — репозиторий, у которого спорных коммитов НЕТ, а предпосылки ЕСТЬ.
DEFAULT_CONTROL = pathlib.Path.home() / "Documents" / "SPA_mirror"
DEFAULT_KEEP = 14

_GIT_TIMEOUT_S = 600


class NotMeasured(Exception):
    """Вопрос задан, ответа нет. Причина обязана быть ЗАМЕРОМ, а не догадкой."""


def _git(root: pathlib.Path | str, *args: str, timeout: int = _GIT_TIMEOUT_S) -> str:
    """Зов git в НАЗВАННОМ репозитории. Любой сбой — `NotMeasured`, а не пустая строка.

    Пустая строка на месте отказа сделала бы «git не ответил» неотличимым от «ничего не
    нашлось» — ровно подмена, запрещённая инв. #17.
    """
    cmd = ["git", "-C", str(root), *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise NotMeasured(f"git не найден: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise NotMeasured(f"git не ответил за {timeout} с: {' '.join(args[:3])}") from exc
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip().splitlines()
        raise NotMeasured(
            f"git {' '.join(args[:3])} ⇒ код {p.returncode}: {err[0] if err else 'без вывода'}")
    return p.stdout


def _refs(root: pathlib.Path | str, prefix: str) -> list[str]:
    out = _git(root, "for-each-ref", "--format=%(refname)", prefix)
    return [ln.strip() for ln in out.split("\n") if ln.strip()]


def stranded(root: pathlib.Path | str) -> dict:
    """Что локально ЕСТЬ и на удалённом НЕ лежит.

    База исключения — ВСЕ `refs/remotes/origin/*`, а не один `origin/main`, и разница
    измерена: против `origin/main` локально «не достижимы» 27 686 коммитов, а против всех
    origin-рефов — **1345**. Первое число отвечает на вопрос «не на главной ветке» и к
    сохранности отношения не имеет: коммит, лежащий на `origin/<другая-ветка>`, НЕ потерян.
    Ошибиться эта мера обязана в сторону СОХРАНЕНИЯ: лишний коммит в bundle стоит байтов,
    недостающий стоит работы.
    """
    heads = _refs(root, HEADS_PREFIX)
    origin = _refs(root, ORIGIN_PREFIX)
    if not heads:
        raise NotMeasured(f"локальных ветвей не нашлось вовсе в {root} — это не «нечего "
                          f"сохранять», а нечитаемый репозиторий")
    if not origin:
        # Без базы «локальное» неотличимо от «всего»: мы бы объявили резервом полную
        # историю и назвали бы это находкой. Fail-CLOSED.
        raise NotMeasured(f"ни одного `{ORIGIN_PREFIX}*` в {root} — база исключения "
                          f"отсутствует, «локально-только» спросить нечем")

    excl = [f"^{r}" for r in origin]
    count_out = _git(root, "rev-list", "--count", *heads, *excl).strip()
    try:
        total = int(count_out)
    except ValueError as exc:
        raise NotMeasured(f"число коммитов не разобрано: {count_out!r}") from exc

    by_head: dict[str, int] = {}
    for ref in heads:
        n = _git(root, "rev-list", "--count", ref, *excl).strip()
        try:
            k = int(n)
        except ValueError as exc:
            raise NotMeasured(f"число коммитов рефа {ref} не разобрано: {n!r}") from exc
        if k:
            by_head[ref] = k

    return {
        "state": HAVE_WORK if total else NOTHING,
        "commits": total,
        "heads_total": len(heads),
        "origin_refs": len(origin),
        "by_head": dict(sorted(by_head.items(), key=lambda kv: -kv[1])),
        "excludes": excl,
        "heads": heads,
    }


def bundle_name(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"spa_stranded_{now.strftime('%Y-%m-%dT%H%M%SZ')}.bundle"


def build(root: pathlib.Path | str, dest: pathlib.Path, meas: dict,
          now: datetime | None = None) -> pathlib.Path:
    """Записать bundle атомарно: временный файл В ТОМ ЖЕ каталоге + `os.replace` (инв. #5).

    Частично записанный bundle под итоговым именем — худший исход из возможных: он выглядит
    резервом и им не является.
    """
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise NotMeasured(f"каталог назначения {dest} не создан: {exc}") from exc

    final = dest / bundle_name(now)
    fd, tmp = tempfile.mkstemp(dir=str(dest), suffix=".bundle.tmp")
    os.close(fd)
    try:
        _git(root, "bundle", "create", tmp, *meas["heads"], *meas["excludes"])
        if not os.path.getsize(tmp):
            raise NotMeasured("git написал bundle нулевого размера")
        os.replace(tmp, final)
    except BaseException:
        # Любой выход — включая KeyboardInterrupt — не оставляет мусора под .tmp.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return final


def _object_store(root: pathlib.Path | str) -> str:
    """Адрес ОБЪЕКТНОГО СКЛАДА, а не рабочего каталога.

    Линкованный worktree — ДРУГОЙ каталог и ТОТ ЖЕ склад (`--git-common-dir` общий), поэтому
    сверять пути рабочих деревьев здесь нельзя: `SPA_wt_c1249` выглядит «чужим», а объекты у
    него те же, и проверка в нём была бы такой же тавтологией, как в самом клоне.
    """
    out = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return os.path.realpath(out)


def verify(bundle: pathlib.Path, control: pathlib.Path,
           root: pathlib.Path | str | None = None) -> dict:
    """Проверить bundle в ЧУЖОМ репозитории. В клоне-источнике это тавтология (см. модуль).

    Отсутствие контрольного репозитория — НЕ «проверено» и НЕ «сломано», а третий исход
    с названной причиной.
    """
    if not control.exists():
        return {"state": UNVERIFIED, "why": f"контрольного репозитория нет: {control}",
                "control": str(control), "heads": [], "prereqs": []}
    try:
        _git(control, "rev-parse", "--git-dir")
    except NotMeasured as exc:
        return {"state": UNVERIFIED, "why": f"контроль не репозиторий: {exc}",
                "control": str(control), "heads": [], "prereqs": []}
    if root is not None:
        # ТАВТОЛОГИЯ ОТВЕРГАЕТСЯ. У источника все предпосылки на месте по построению, поэтому
        # `bundle verify` там успешен ВСЕГДА — включая случай, когда bundle пуст по существу.
        # Такой зелёный ответ и есть «ответ на свой вопрос вместо нужного».
        try:
            same = _object_store(control) == _object_store(root)
        except NotMeasured as exc:
            return {"state": UNVERIFIED,
                    "why": f"склад объектов не спрошен, а без него тавтологию не отличить: "
                           f"{exc}",
                    "control": str(control), "heads": [], "prereqs": []}
        if same:
            return {"state": UNVERIFIED,
                    "why": f"контроль делит объектный склад с источником "
                           f"({_object_store(root)}) — проверка в нём ТАВТОЛОГИЧНА и "
                           f"о восстановимости не говорит ничего",
                    "control": str(control), "heads": [], "prereqs": []}
    try:
        out = _git(control, "bundle", "verify", str(bundle))
    except NotMeasured as exc:
        # Самый частый и самый важный случай: предпосылок у контроля нет (зеркало отстало).
        # Это именно НЕ ИЗМЕРЕНО: о восстановимости bundle мы так ничего и не узнали.
        return {"state": UNVERIFIED, "why": str(exc), "control": str(control),
                "heads": [], "prereqs": []}
    heads, prereqs = [], []
    for ln in out.split("\n"):
        s = ln.strip()
        if not s:
            continue
        parts = s.split()
        if len(parts) >= 2 and len(parts[0]) == 40 and parts[1].startswith("refs/"):
            heads.append(s)
        elif len(parts) == 1 and len(parts[0]) == 40:
            prereqs.append(parts[0])
    if not heads:
        return {"state": UNVERIFIED,
                "why": "в выводе `bundle verify` не названо ни одного рефа — "
                       "о СОСТАВЕ bundle не сказано ничего",
                "control": str(control), "heads": [], "prereqs": prereqs}
    return {"state": VERIFIED, "why": None, "control": str(control),
            "heads": heads, "prereqs": prereqs}


def prune(dest: pathlib.Path, keep: int) -> list[str]:
    """Убрать старые bundle, оставив `keep` самых свежих. Удаляется ТОЛЬКО своё имя."""
    if keep <= 0:
        return []
    got = sorted(dest.glob("spa_stranded_*.bundle"), key=lambda p: p.name)
    dropped = []
    for p in got[:-keep] if len(got) > keep else []:
        try:
            p.unlink()
            dropped.append(p.name)
        except OSError:
            # Не смогли убрать — не беда и не повод падать: лишний резерв безвреден.
            pass
    return dropped


def run(root: pathlib.Path, dest: pathlib.Path, control: pathlib.Path,
        keep: int = DEFAULT_KEEP, now: datetime | None = None,
        do_build: bool = True) -> dict:
    meas = stranded(root)
    doc = {
        "schema": "spa-stack-bundle/1",
        "root": str(root),
        "measured_at": (now or datetime.now(timezone.utc)).isoformat(),
        "commits": meas["commits"],
        "heads_total": meas["heads_total"],
        "origin_refs": meas["origin_refs"],
        "by_head": meas["by_head"],
        "bundle": None,
        "bytes": None,
        "verify": None,
        "pruned": [],
    }
    if meas["state"] == NOTHING:
        # ИЗМЕРЕННЫЙ ноль: каждый локальный реф достижим от origin.
        doc["state"] = NOTHING
        return doc
    if not do_build:
        doc["state"] = UNMEASURED
        doc["why"] = "запрошен только замер (--measure-only) — bundle не писался"
        return doc

    path = build(root, dest, meas, now=now)
    doc["bundle"] = str(path)
    doc["bytes"] = os.path.getsize(path)
    ver = verify(path, control, root=root)
    doc["verify"] = ver
    doc["pruned"] = prune(dest, keep)
    if ver["state"] != VERIFIED:
        doc["state"] = UNMEASURED
        doc["why"] = (f"bundle записан ({path}), но НЕ ПРОВЕРЕН: {ver['why']} — "
                      f"резервом он не зовётся")
        return doc
    doc["state"] = BUNDLED
    return doc


def report(doc: dict) -> list[str]:
    out: list[str] = []
    if doc["state"] == NOTHING:
        out.append(f"✅ сохранять нечего: все {doc['heads_total']} локальных ветв(ей) "
                   f"достижимы от {doc['origin_refs']} origin-рефов — ИЗМЕРЕННЫЙ ноль")
        return out
    out.append(f"работа, которой нет ни на одном origin-рефе: {doc['commits']} коммит(ов) "
               f"(локальных ветвей {doc['heads_total']}, origin-рефов {doc['origin_refs']})")
    for ref, n in list(doc["by_head"].items())[:12]:
        out.append(f"   {n:>6}  {ref}")
    more = len(doc["by_head"]) - 12
    if more > 0:
        out.append(f"   … и ещё {more} ветв(ей) с неотправленными коммитами")
    if doc.get("bundle"):
        out.append(f"bundle: {doc['bundle']} ({doc['bytes']} Б)")
    ver = doc.get("verify") or {}
    if doc["state"] == BUNDLED:
        out.append(f"✅ ПРОВЕРЕН в чужом репозитории {ver.get('control')}: "
                   f"рефов {len(ver.get('heads', []))}, предпосылок "
                   f"{len(ver.get('prereqs', []))} (лежат на origin — репозиторий публичный, "
                   f"их чтение ключа НЕ требует)")
    else:
        out.append(f"⛔ НЕ ИЗМЕРЕНО: {doc.get('why')}")
    if doc.get("pruned"):
        out.append(f"убрано старых: {len(doc['pruned'])}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Вторая копия работы, которой нельзя уехать на origin "
                    "(проверенный git bundle вне клона).")
    ap.add_argument("--repo-root", default=str(DEFAULT_ROOT), type=pathlib.Path,
                    help="репозиторий, чью неотправленную работу сохраняем "
                         f"(умолчание {DEFAULT_ROOT} — ПЕЧАТАЕТСЯ)")
    ap.add_argument("--dest", default=str(DEFAULT_DEST), type=pathlib.Path,
                    help=f"каталог для bundle, ВНЕ клона (умолчание {DEFAULT_DEST})")
    ap.add_argument("--control-repo", default=str(DEFAULT_CONTROL), type=pathlib.Path,
                    help="ЧУЖОЙ репозиторий, в котором bundle проверяется "
                         f"(умолчание {DEFAULT_CONTROL})")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                    help=f"сколько свежих bundle оставлять (умолчание {DEFAULT_KEEP})")
    ap.add_argument("--measure-only", action="store_true",
                    help="только замер, без записи (исход 2: резерва не возникло)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = pathlib.Path(args.repo_root).expanduser()
    if str(root) == str(DEFAULT_ROOT):
        # Дерево ПЕЧАТАЕТСЯ даже когда досталось умолчанию: молчаливый выбор дерева —
        # предмет `.claude/rules/deployment.md` § ДЕРЕВО, ИЗ КОТОРОГО ЧИТАЮТСЯ БАЙТЫ.
        print(f"дерево досталось УМОЛЧАНИЮ: {root}", file=sys.stderr)

    try:
        doc = run(root, pathlib.Path(args.dest).expanduser(),
                  pathlib.Path(args.control_repo).expanduser(),
                  keep=args.keep, do_build=not args.measure_only)
    except NotMeasured as exc:
        print(f"⛔ НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        if args.json:
            print(json.dumps({"schema": "spa-stack-bundle/1", "state": UNMEASURED,
                              "why": str(exc)}, ensure_ascii=False))
        return 2

    if args.json:
        print(json.dumps(doc, ensure_ascii=False))
    else:
        for line in report(doc):
            print(line)

    if doc["state"] == BUNDLED:
        return 0
    if doc["state"] == NOTHING:
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
