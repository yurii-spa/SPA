#!/usr/bin/env python3
"""Содержимое рабочих деревьев, у которого НЕТ ВТОРОЙ КОПИИ ни в одном складе.

Заказ G1087 п. 4 (цикл #1249), дословно: «население „что ещё живёт в одном складе“ за
пределами git-коммитов НЕ ИЗМЕРЕНО и нулём не считается: незакоммиченные правки рабочих
деревьев не видит ни один bundle».

**Почему вопрос не академический.** Резерв `scripts/stack_bundle.py` (ADR-1104) пакует
`refs/heads/*` минус достижимое от origin — то есть КОММИТЫ. Байты, которые ещё не вошли
ни в один коммит, в связку не попадают ПО ПОСТРОЕНИЮ, и связка об этом НЕ ГОВОРИТ: её
вердикт «резерв записан и проверен» верен про коммиты и ничего не утверждает про диск.

**Известный член класса — не выдумка, а авария.** Цикл #1242 умер между последней правкой
и коммитом: вся работа ADR-1097 (1640 строк в 10 файлах) осталась НЕЗАКОММИЧЕННОЙ в
индексе одноразовых деревьев `/private/tmp/spa_c1242*`, а запись цикла уже числила стек
выросшим. Подняла её рука цикла #1243, и только потому, что `/private/tmp` ещё не успел
вычиститься системой. Связка в тот момент сохранила бы стек БЕЗ этой работы и вышла бы
кодом 0.

## Решающая ось — ДОСТИЖИМОСТЬ, а не отличие от HEAD

Первая редакция замера спрашивала «отличается ли файл от HEAD своего дерева» и ответила
**5906** записей в 118 деревьях из 179. Это ответ в сторону находки, и он ложен: прод-дерево
отстаёт от origin на 127 коммитов, поэтому почти всё «изменённое» в нём УЖЕ ЛЕЖИТ на
origin — потеряться не может. Вопрос обязан звучать иначе:

> достижимы ли ЭТИ БАЙТЫ хоть от одного рефа — `refs/heads/*` (их пакует связка) либо
> `refs/remotes/origin/*` (они уже вне машины)?

Недостижимы ⇒ единственная копия есть файл на диске.

**Существование объекта ответом НЕ является, и разница измерима.** `git add` кладёт blob в
склад, оставляя его недостижимым ни от одного рефа — ровно состояние #1242. Мера на
`git cat-file -e` назвала бы такую работу сохранённой, потому что объект ЕСТЬ. Мера на
достижимости называет её членом. Поэтому ось — достижимость, и сцена
`test_staged_but_uncommitted_is_named` держит именно это различие.

## Родов четыре, и у каждого НАЗВАННАЯ причина, а не удобство

| род | что это | почему в предмете или нет |
|---|---|---|
| `work` | код, доки, карточки, правила, сайт | **ПРЕДМЕТ**: второй копии нет нигде |
| `state` | `data/**` | у него СВОЙ резерв — `com.spa.daily_backup` пишет `data/backups/spa_state_<дата>.tar.gz`; прибор его НАЛИЧИЕ СПРАШИВАЕТ, а не предполагает |
| `derived` | путь, объявленный производимым в `architecture/*.json` | потеря стóит одного прогона производителя, а не работы |
| `deletion` | запись об удалении | старые байты лежат в коммите — удаление обратимо |

Отсев `derived` и `state` — ВЫЧИТАНИЕ ИЗ ПРЕДМЕТА, поэтому он обязан быть измеренным, а
не заявленным: род печатается у каждого имени, а не сворачивается в счётчик.

**Игнорируемое git отсеивает САМ.** `git status` без `--ignored` не перечисляет `.gitignore`,
поэтому `__pycache__`, `.pytest_cache`, `*.pyc` в поверхность не входят — это структурный
фильтр дерева, а не список-исключение, который пришлось бы поддерживать.

## Три исхода различимы (инв. #17)

* **0** — предмет ПУСТ: **измеренный** ноль работы без второй копии;
* **1** — НАЙДЕНО: имена названы, с деревом, родом и размером;
* **2** — **НЕ ИЗМЕРЕНО** с названной причиной (git не ответил · дерева нет на диске ·
  множество достижимых не построено · бюджет времени исчерпан). Ноль при этом НЕ
  печатается: «не спросили» обязано отличаться от «спросили, и пусто».

Дерево, которое не прочиталось, не делает ответ приблизительным — оно НАЗЫВАЕТСЯ в
`unmeasured`, и ответ о населении остаётся ответом о ПРОЧИТАННОЙ поверхности. Нулём
непрочитанное не считается.

## Прибор ТОЛЬКО ЧИТАЕТ, и это проверяется, а не обещается

`git hash-object` зовётся **без** `-w`, то есть склад объектов не растёт ни на байт.
Положительный контроль — `test_the_prober_does_not_write_to_the_object_store`: число
объектов склада до и после прогона сверяется, и расхождение краснит.

## Чего это НЕ закрывает

Вопрос задаётся деревьям, которые git ПЕРЕЧИСЛЯЕТ (`git worktree list`). Каталог с работой,
снятый с регистрации или скопированный мимо git, этой мерой не судится, и население за её
пределами НЕ ИЗМЕРЕНО — нулём это не считается. Прибор НАЗЫВАЕТ, а не сохраняет: вынос
второй копии на внешний носитель есть предмет №3 границы ADR-285 (публикация вовне), то
есть решение владельца, а не умолчание модуля. И «у рода `state` резерв есть» — про
наличие архива, а НЕ про то, что он лежит на другом диске: `data/backups/` живёт на том же.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import glob
import json
import os
import pathlib
import subprocess
import sys
import time

# Исходы. Имена — часть вердикта (инв. #17): `empty` это ИЗМЕРЕННЫЙ ноль, `unmeasured` —
# его отсутствие, и подставлять одно вместо другого запрещено.
EMPTY, FOUND, UNMEASURED = "empty", "found", "unmeasured"

# Роды. Предметом является РОВНО один; остальные три вычитаются по НАЗВАННОЙ причине.
WORK, STATE, DERIVED, DELETION = "work", "state", "derived", "deletion"
SUBJECT_KIND = WORK

# ВТОРАЯ ось предмета, и она не косметика: счётчик её сглаживает, а чинится она разным.
# `WHOLE` — файла нет ни в одном коммите ВООБЩЕ, потеря полная.
# `DELTA` — отслеживаемый файл правлен: базовые байты лежат в коммите, под риском правка.
# Замер #1269 (27.11): 439 ПОЛНЫХ против 330 правок — ответ «769 файлов» скрыл бы, что у
# 330 из них база в коммите цела. Числа ДАТИРОВАНЫ намеренно: #1256 оставил здесь
# «416 против 309 … 725», а в своём же ADR «415 против 297 … 712» — два несовместимых
# снимка ОДНОГО дня. Перепечатывать их нельзя, мерить обязан прибор.
WHOLE, DELTA = "whole", "delta"

# Вопрос оси — «есть ли ЭТОТ ПУТЬ в коммите», и он задаётся КОДОМ СОСТОЯНИЯ, а не
# одним `??`. Первая редакция спрашивала ровно `xy == "??"` и назвала ПОЛНУЮ потерю
# «только правкой» у `git add`-нутого нового файла: его статус `A `, пути в HEAD нет,
# а ось отвечала `delta`. Нашла это ПРОБА приёмки, не вычитка. Спрашивать `git cat-file
# -e HEAD:<путь>` у каждого файла честнее, но это +5907 подпроцессов на прогон, а код
# состояния отвечает на тот же вопрос без них.
# `R`/`C` (переименование/копия) остаются `delta` НАЗВАННО: байты исходного пути лежат
# в коммите, то есть потеря не полна.
_WHOLE_INDEX_CODES = ("A",)

HEADS_PREFIX = "refs/heads/"
ORIGIN_PREFIX = "refs/remotes/origin/"

# Каталоги, чьё содержимое есть РАБОТА. Перечень нарочно по КАТАЛОГУ, а не по расширению:
# расширение не говорит, кто автор байтов.
WORK_PREFIXES = (
    "spa_core/", "scripts/", "tests/", "studio_shell/", "research/", "architecture/",
    "docs/", "nimbalyst-local/", ".claude/", "landing/", "inbox/", "launchd/",
)
# Состояние: живой трек и всё, что пишет флот. У него СВОЙ резерв, и прибор его спрашивает.
STATE_PREFIXES = ("data/",)
# Боковые файлы sqlite — состояние движка, а не работа; потеря безвредна по построению.
# `.db` сюда входит НАЗВАННО: единственная база дерева — `spa_core/database/spa.db`,
# её пишет флот, и потеря стóит прогона, а не работы. Боковые файлы sqlite тем более.
STATE_SUFFIXES = (".db", ".db-shm", ".db-wal", ".db-journal")

DEFAULT_ROOT = pathlib.Path.home() / "Documents" / "SPA_Claude"
_GIT_TIMEOUT_S = 600
# Бюджет: исчерпан ⇒ НЕ ИЗМЕРЕНО с названной причиной, а не «успели столько, вот ответ».
DEFAULT_BUDGET_S = 900.0


class NotMeasured(Exception):
    """Вопрос задан, ответа нет. Причина обязана быть ЗАМЕРОМ, а не догадкой."""


def _git(cwd, *args, timeout: int = _GIT_TIMEOUT_S) -> str:
    """Зов git в НАЗВАННОМ каталоге. Любой сбой — `NotMeasured`, не пустая строка."""
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:         # noqa: BLE001
        raise NotMeasured(f"`git {' '.join(args)}` в {cwd}: "
                          f"{type(exc).__name__}: {exc}") from exc
    if r.returncode != 0:
        raise NotMeasured(f"`git {' '.join(args)}` в {cwd} rc={r.returncode} "
                          f"{r.stderr.strip()[:160]!r}")
    return r.stdout


def refs(root, prefix: str, git=_git) -> list[str]:
    """Полные имена рефов под префиксом."""
    out = git(root, "for-each-ref", "--format=%(refname)", prefix)
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def reachable_objects(root, git=_git) -> set[str]:
    """Объекты, достижимые от `refs/heads/*` ∪ `refs/remotes/origin/*`.

    ДВА склада, а не один: связка пакует первое, origin держит второе. Недостижимое от
    обоих и есть содержимое без второй копии.

    Рефов нет вовсе ⇒ `NotMeasured`: пустое множество объявило бы членом КАЖДЫЙ файл,
    то есть выдало бы сломанный вопрос за находку обо всём дереве.

    **СВЕЖЕСТЬ `refs/remotes/origin/*` здесь НЕ ДОКАЗАНА, и это НАЗВАННЫЙ выбор, а не
    упущение** (храповик ADR-362/1112 числит этот зов своим членом — верно по его
    мерке). Три причины, и каждая проверяема:

    1. **Устаревшая ссылка ошибается В СТОРОНУ НАХОДКИ.** Чем старее `origin/*`, тем
       МЕНЬШЕ объектов она знает ⇒ тем БОЛЬШЕ содержимого прибор назовёт лишённым
       второй копии. Это ровно та сторона, в которую этой мере предписано ошибаться
       (см. `kind_of`), в отличие от классического предмета храповика, где устаревшая
       ссылка даёт ложное «чисто».
    2. **`git fetch` здесь ЗАПРЕЩЁН** (`.claude/rules/deployment.md`, § тринадцатая
       дверь, п. 4): он сдвинул бы `refs/remotes/origin/*`, на которую в том же
       прогоне опираются соседние гейты. Прибор, меняющий ответ соседям, хуже
       прибора, молчащего о своей свежести.
    3. **Спросить сервер прибору НЕЧЕМ:** он не доставка и ответа `ls-remote` не
       имеет, а ходить в сеть самому значило бы превратить читающую меру в сетевую.

    Отсюда граница, сказанная вслух: ответ про «вторую копию вне машины» дан о том
    origin, который ЗНАЕТ ЭТОТ КЛОН, а не о сервере. Доставка прошла с объявленным
    обходом `--allow-ungated-ref-read` (цикл #1269, ADR-1123), и обход НАПЕЧАТАН.
    """
    names = refs(root, HEADS_PREFIX, git=git) + refs(root, ORIGIN_PREFIX, git=git)
    if not names:
        raise NotMeasured(f"ни одного рефа под {HEADS_PREFIX} и {ORIGIN_PREFIX} — "
                          f"множество достижимых не построить, и пустое множество "
                          f"ответом НЕ является")
    out = git(root, "rev-list", "--objects", *names)
    got: set[str] = set()
    for ln in out.splitlines():
        sp = ln.find(" ")
        got.add(ln[:sp] if sp > 0 else ln)
    if not got:
        raise NotMeasured(f"`rev-list --objects` по {len(names)} рефам вернул пусто")
    return got


def worktrees(root, git=_git) -> tuple[list[str], list[tuple[str, str]]]:
    """``(пути деревьев, [(путь, причина) НЕ ИЗМЕРЕНО])``.

    Главное дерево git перечисляет ПЕРВЫМ — порядок сохраняется, чтобы отчёт начинался
    с того дерева, в котором живёт прод.
    """
    out = git(root, "worktree", "list", "--porcelain")
    paths: list[str] = []
    for ln in out.splitlines():
        if ln.startswith("worktree "):
            paths.append(ln[len("worktree "):].strip())
    if not paths:
        raise NotMeasured("`git worktree list` не назвал ни одного дерева")
    alive, gone = [], []
    for p in paths:
        (alive if os.path.isdir(p) else gone).append(p)
    return alive, [(p, "каталога нет на диске") for p in gone]


def declared_produced(root) -> tuple[set[str], str | None]:
    """Пути, объявленные ПРОИЗВОДИМЫМИ в конституции ``architecture/*.json``.

    Отсев рода `derived` держится на ОБЪЯВЛЕНИИ, а не на догадке по имени файла.
    Ни одного объявления не прочитано ⇒ возвращается причина, и род `derived` в этом
    прогоне не вычитается ВООБСЕ: лучше назвать производное работой, чем молча вычесть
    работу как производное.
    """
    found: set[str] = set()
    read = 0
    pattern = os.path.join(str(root), "architecture", "*.json")
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        read += 1
        _harvest_paths(doc, found)
    if read == 0:
        return set(), f"ни одного объявления не прочитано по {pattern}"
    return found, None


_PATH_KEYS = ("produces", "artifact", "artifacts", "path", "produces_paths")


def _harvest_paths(node, out: set[str]) -> None:
    """Сбор объявленных путей. Ключ, похожий на путь, берётся и из ключей словаря:
    конституция объявляет артефакты и значением, и ключом."""
    if isinstance(node, dict):
        for key, val in node.items():
            if key in _PATH_KEYS:
                if isinstance(val, str):
                    out.add(val)
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, str):
                            out.add(item)
                        else:
                            _harvest_paths(item, out)
                elif isinstance(val, dict):
                    for kk, vv in val.items():
                        if isinstance(kk, str) and ("/" in kk or kk.endswith(".json")):
                            out.add(kk)
                        _harvest_paths(vv, out)
            else:
                _harvest_paths(val, out)
    elif isinstance(node, list):
        for item in node:
            _harvest_paths(item, out)


def kind_of(rel_path: str, produced: set[str]) -> str:
    """Род пути. Порядок проверок — часть смысла: состояние и производное ВЫЧИТАЮТСЯ
    из работы, поэтому спрашиваются раньше."""
    if rel_path.startswith(STATE_PREFIXES) or rel_path.endswith(STATE_SUFFIXES):
        return STATE
    if rel_path in produced:
        return DERIVED
    if rel_path.startswith(WORK_PREFIXES):
        return WORK
    # Корневой файл без объявленного рода. Работой он называется НАМЕРЕННО: ошибаться
    # эта мера обязана в сторону находки, а не в сторону «чисто».
    return WORK


def _status_rows(tree: str, git=_git) -> list[tuple[str, str]]:
    """``[(xy, относительный путь)]`` из `git status --porcelain=v1 -uall`.

    `core.quotepath=false` — иначе путь с кириллицей приезжает в восьмеричных экранах и
    `os.path.isfile` по нему не находит файла, то есть ЧИТАЕМЫЙ файл попал бы в
    «НЕ ИЗМЕРЕНО» (замер первой редакции: так ушли 9 имён).
    """
    out = git(tree, "-c", "core.quotepath=false", "status", "--porcelain=v1", "-uall")
    rows = []
    for ln in out.splitlines():
        if not ln.strip() or len(ln) < 4:
            continue
        xy, path = ln[:2], ln[3:]
        if " -> " in path:                      # переименование: судим НОВОЕ имя
            path = path.split(" -> ")[-1]
        rows.append((xy, path.strip().strip('"')))
    return rows


def blob_of(tree: str, abs_path: str, git=_git) -> str:
    """sha байтов НА ДИСКЕ. Без `-w` — склад объектов не растёт (см. докстринг модуля)."""
    out = git(tree, "hash-object", "--", abs_path, timeout=60)
    sha = out.strip()
    if not sha:
        raise NotMeasured(f"`hash-object` вернул пусто для {abs_path}")
    return sha


def state_reserve(root) -> dict:
    """Есть ли у рода `state` та вторая копия, на которую ссылается его вычитание.

    Три исхода, потому что «архив есть» обязано отличаться и от «архивов нет», и от
    «каталога резервов не видно»: вычитание рода из предмета держится на ЭТОМ ответе.
    """
    backups = os.path.join(str(root), "data", "backups")
    if not os.path.isdir(backups):
        return {"verdict": UNMEASURED, "reason": f"каталога {backups} нет",
                "newest": None, "age_hours": None}
    archives = sorted(glob.glob(os.path.join(backups, "spa_state_????-??-??.tar.gz")))
    if not archives:
        return {"verdict": EMPTY, "reason": "ни одного архива spa_state_*.tar.gz",
                "newest": None, "age_hours": None}
    newest = archives[-1]
    age = (time.time() - os.path.getmtime(newest)) / 3600.0
    return {"verdict": FOUND, "reason": None, "newest": newest,
            "age_hours": round(age, 1)}


def _out_of_budget(doc: dict, where: str, budget_s: float, elapsed: float) -> dict:
    """Бюджет исчерпан ⇒ НЕ ИЗМЕРЕНО с названной причиной.

    Наблюдённые имена при этом НЕ ВЫБРАСЫВАЮТСЯ, а переезжают в `names_partial`:
    выбросить состоявшееся наблюдение и доложить о нём «не измерено» — зеркальный
    дефект инв. #17, найденный ADR-1079. Но и ПОПУЛЯЦИЕЙ они не зовутся: `names`
    пусто, потому что частичный список прочитался бы как ответ о населении.
    """
    doc["names_partial"] = doc["names"]
    doc["names"] = []
    doc["unmeasured"].append([where, f"бюджет {budget_s} с исчерпан за {elapsed:.1f} с — "
                                     f"поверхность после этой точки НЕ ПРОЧИТАНА"])
    doc["verdict"] = UNMEASURED
    doc["elapsed_s"] = round(elapsed, 1)
    return doc


def measure(root=None, git=_git, budget_s: float = DEFAULT_BUDGET_S,
            now=None) -> dict:
    """Замер населения. Прибор ТОЛЬКО ЧИТАЕТ."""
    root = pathlib.Path(root or DEFAULT_ROOT)
    # `None` означает «бюджет не назван» и обязан дать УМОЛЧАНИЕ, а не падение:
    # сравнение с `None` уронило бы меру в `TypeError`, и проводка доложила бы о ней
    # «НЕ ИЗМЕРЕНО» — то есть отсутствие входа стало бы отсутствием ответа.
    budget_s = DEFAULT_BUDGET_S if budget_s is None else float(budget_s)
    clock = now or time.monotonic
    started = clock()
    doc: dict = {
        "root": str(root), "trees_declared": 0, "trees_read": 0,
        "rows_total": 0, "by_kind": {}, "by_loss": {}, "names": [],
        "names_partial": [], "unmeasured": [],
        "state_reserve": None, "produced_declared": 0, "produced_reason": None,
        "verdict": None, "budget_s": budget_s, "elapsed_s": None,
    }
    try:
        reach = reachable_objects(root, git=git)
        alive, gone = worktrees(root, git=git)
    except NotMeasured as exc:
        doc["verdict"] = UNMEASURED
        doc["unmeasured"].append(["<корень>", str(exc)])
        doc["elapsed_s"] = round(clock() - started, 1)
        return doc
    doc["reachable_objects"] = len(reach)
    doc["trees_declared"] = len(alive) + len(gone)
    doc["unmeasured"].extend([list(g) for g in gone])
    produced, prod_reason = declared_produced(root)
    doc["produced_declared"] = len(produced)
    doc["produced_reason"] = prod_reason
    doc["state_reserve"] = state_reserve(root)

    by_kind: dict[str, int] = {}
    for tree in alive:
        if clock() - started > budget_s:
            doc["by_kind"] = by_kind
            return _out_of_budget(doc, tree, budget_s, clock() - started)
        try:
            rows = _status_rows(tree, git=git)
        except NotMeasured as exc:
            doc["unmeasured"].append([tree, str(exc)])
            continue
        doc["trees_read"] += 1
        for xy, rel in rows:
            if clock() - started > budget_s:
                doc["by_kind"] = by_kind
                return _out_of_budget(doc, f"{tree}::{rel}", budget_s,
                                      clock() - started)
            doc["rows_total"] += 1
            if "D" in xy:
                by_kind[DELETION] = by_kind.get(DELETION, 0) + 1
                continue
            full = os.path.join(tree, rel)
            if not os.path.isfile(full):
                doc["unmeasured"].append([full, "не обычный файл"])
                continue
            try:
                sha = blob_of(tree, full, git=git)
            except NotMeasured as exc:
                doc["unmeasured"].append([full, str(exc)])
                continue
            if sha in reach:
                continue                        # вторая копия ЕСТЬ — не член
            kind = kind_of(rel, produced)
            by_kind[kind] = by_kind.get(kind, 0) + 1
            if kind == SUBJECT_KIND:
                loss = (WHOLE if (xy == "??" or any(c in xy
                                                    for c in _WHOLE_INDEX_CODES))
                        else DELTA)
                doc["by_loss"][loss] = doc["by_loss"].get(loss, 0) + 1
                doc["names"].append({"tree": tree, "path": rel, "xy": xy, "kind": kind,
                                     "loss": loss, "bytes": os.path.getsize(full),
                                     "sha": sha})
    doc["by_kind"] = by_kind
    doc["elapsed_s"] = round(clock() - started, 1)
    doc["verdict"] = FOUND if doc["names"] else EMPTY
    return doc


def report(doc: dict) -> list[str]:
    """Строки отчёта. Ноль печатается ТОЛЬКО когда он измерен."""
    out = [f"содержимое без ВТОРОЙ копии — замер в {doc['root']}"]
    if doc["verdict"] == UNMEASURED:
        out.append("⚠️ НЕ ИЗМЕРЕНО — ответа о населении НЕТ, и нулём это не считается:")
        for path, reason in doc["unmeasured"][:10]:
            out.append(f"   · {path}: {reason}")
        if len(doc["unmeasured"]) > 10:
            out.append(f"   … и ещё {len(doc['unmeasured']) - 10}")
        part = doc.get("names_partial") or []
        if part:
            out.append(f"   наблюдённое ДО остановки (это НЕ население, а то, что "
                       f"успели увидеть): {len(part)} файл(ов)")
        return out
    out.append(f"деревьев объявлено {doc['trees_declared']} · ПРОЧИТАНО "
               f"{doc['trees_read']} · записей состояния {doc['rows_total']} · "
               f"достижимых объектов {doc.get('reachable_objects', '?')}")
    kinds = doc["by_kind"]
    subject = len(doc["names"])
    out.append(f"недостижимо ни от одного рефа, по роду: "
               f"РАБОТА {kinds.get(WORK, 0)} · состояние {kinds.get(STATE, 0)} · "
               f"производное {kinds.get(DERIVED, 0)} · удаление {kinds.get(DELETION, 0)}")
    res = doc["state_reserve"] or {}
    if res.get("verdict") == FOUND:
        out.append(f"   вычитание рода «состояние» ОБОСНОВАНО замером: свежий архив "
                   f"{os.path.basename(res['newest'])}, возраст {res['age_hours']} ч "
                   f"(на ТОМ ЖЕ диске — от гибели машины не страхует)")
    else:
        out.append(f"   ⚠️ вычитание рода «состояние» НЕ ОБОСНОВАНО: "
                   f"{res.get('reason')} — архива второй копии не наблюдалось")
    if doc["produced_reason"]:
        out.append(f"   ⚠️ род «производное» НЕ вычитался: {doc['produced_reason']}")
    else:
        out.append(f"   объявленных производимых путей в конституции: "
                   f"{doc['produced_declared']}")
    if subject == 0:
        out.append("✅ ПРЕДМЕТ ПУСТ — работы без второй копии не наблюдалось "
                   "(ИЗМЕРЕННЫЙ ноль по прочитанной поверхности)")
    else:
        total_b = sum(n["bytes"] for n in doc["names"])
        loss = doc["by_loss"]
        out.append(f"❌ НАЙДЕНО {subject} файл(ов) работы без второй копии "
                   f"({total_b} Б) — единственная копия есть файл на диске:")
        out.append(f"   потеря ПОЛНАЯ (файла нет ни в одном коммите): "
                   f"{loss.get(WHOLE, 0)} · под риском только ПРАВКА "
                   f"(база в коммите цела): {loss.get(DELTA, 0)}")
        per_tree: dict[str, int] = {}
        for n in doc["names"]:
            per_tree[n["tree"]] = per_tree.get(n["tree"], 0) + 1
        for tree, cnt in sorted(per_tree.items(), key=lambda x: -x[1])[:10]:
            out.append(f"   {cnt:5d}  {tree}")
        if len(per_tree) > 10:
            out.append(f"   … и ещё {len(per_tree) - 10} дерев(о/а)")
        # Сумма байт без НАЗВАННЫХ крупнейших вводит в заблуждение: замер #1256 дал
        # 3,0 ГБ, и почти всё это четыре локальных tar.gz, то есть резервы ЧУЖОГО, а
        # не работа. Счётчик файлов и вес отвечают на РАЗНЫЕ вопросы.
        biggest = sorted(doc["names"], key=lambda n: -n["bytes"])[:3]
        out.append("   крупнейшие по весу (вес и число файлов — РАЗНЫЕ вопросы): "
                   + " · ".join(f"{n['path']} {n['bytes']} Б" for n in biggest))
    if doc["unmeasured"]:
        out.append(f"⚠️ НЕ ПРОЧИТАНО {len(doc['unmeasured'])} — это НЕ ноль; "
                   f"ответ дан о прочитанной поверхности:")
        for path, reason in doc["unmeasured"][:5]:
            out.append(f"   · {path}: {reason}")
    out.append("ADVISORY: прибор только ЧИТАЕТ — `hash-object` без `-w`, "
               "склад объектов не растёт")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Содержимое рабочих деревьев без ВТОРОЙ копии (заказ G1087 п. 4)")
    ap.add_argument("--repo-root", default=None,
                    help="дерево, о котором спрашиваем (умолчание ПЕЧАТАЕТСЯ)")
    ap.add_argument("--budget-s", type=float, default=DEFAULT_BUDGET_S)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--names", action="store_true", help="печатать имена предмета")
    ns = ap.parse_args(argv)
    root = ns.repo_root or DEFAULT_ROOT
    if ns.repo_root is None:
        print(f"дерево досталось УМОЛЧАНИЮ: {root}", file=sys.stderr)
    if not os.path.isdir(root):
        print(f"⚠️ НЕ ИЗМЕРЕНО: названного дерева {root} нет", file=sys.stderr)
        return 2
    doc = measure(root, budget_s=ns.budget_s)
    if ns.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        for line in report(doc):
            print(line)
        if ns.names:
            for n in doc["names"]:
                print(f"   {n['loss']:5s}  {n['tree']}::{n['path']} "
                      f"({n['bytes']} Б, статус {n['xy']!r})")
    return {EMPTY: 0, FOUND: 1, UNMEASURED: 2}[doc["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
