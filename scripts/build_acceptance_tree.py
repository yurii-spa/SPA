#!/usr/bin/env python3
"""Сборка дерева-приёмки §49 приказа «Portfolio CIO» — решение владельца ADR-509, вариант 1.

Владелец выбрал **отдельное дерево только для чтения**, куда сходятся и
поверхности владельца (`landing/src`, `spa_core/telegram`, `scripts`), и живые
артефакты: ни прод-дерево, ни worktree не могут ответить на §49 целиком, потому
что `landing/` в прод не возится намеренно (ADR-152), а живого `data/` в
worktree нет по построению.

## Почему этот файл появился только 2026-11-04

Дерево на диске существовало с 15.10, и его собственный маркер называл сборщиком
`scripts/build_acceptance_tree.py`. **Этого файла не было никогда** — ни на
одной ветке (`git log --all -- scripts/build_acceptance_tree.py` пуст). То есть
решение владельца выглядело исполненным, потому что каталог есть, а на деле
место приёмки было невоспроизводимо: собравшая его одноразовая команда ушла
вместе с сессией.

Цена этого измерена тем же циклом #1031 в ПОЛНОМ клоне
(`~/Documents/SPA_mirror`; у прод-клона спрашивать нельзя — он усечён, см.
`spa_core/monitoring/acceptance_tree_lineage.history_completeness`):

* код дерева стоял на коммите `167667598` — предке `main`, отставание **519**
  коммитов;
* за эти 519 коммитов изменилась САМА МЕРКА §49:
  `spa_core/monitoring/card_acceptance.py` +7699/-63 (там живут пробы §49) и
  `scripts/cio_acceptance_rollup.py` +98/-1 — то есть дерево вынесло бы вердикт
  ПРОШЛОЙ меркой и не сказало бы об этом ни слова;
* читателя у дерева не было: слова `SPA_acceptance` не было ни в одном файле
  `origin/main`.

Записка не есть инструмент. Сборщик закоммичен ровно поэтому.

## Что этот сборщик делает

1. Достаёт **чистое дерево** объявленной ссылки из объявленного репозитория
   (`git worktree`-независимо: `git archive <ref> | tar -x`), то есть без
   рабочего мусора и без чужого незакоммиченного состояния.
2. Кладёт `data` **ССЫЛКОЙ** на живой каталог, а не копией. Копия устарела бы
   МОЛЧА, и отличить вчерашний замер от сегодняшнего стало бы нечем — дословно
   урок ADR-508, и ровно это уже записано в маркере первой редакции.
3. Снимает право записи со всего дерева (`chmod a-w`), кроме самой ссылки
   `data`: дерево приёмки, в которое можно писать, становится вторым
   прод-деревом.
4. Пишет маркер `.acceptance_tree.json` — с объявленной ссылкой, **разрешённым
   коммитом**, путём К СЕБЕ (`builder`) и вердиктом родословной на момент
   сборки.

## Чего он НЕ делает

* **Не угадывает ссылку.** Умолчание — `origin/main`, и оно объявлено.
* **Не трогает живой `data/`.** Ссылка односторонняя: дерево читает, не пишет.
* **Не судит о §49.** Вердикты критериев снимает сводка; сборщик делает место,
  где её можно позвать.
* **Не чинит расхождение.** Собрать дерево НЕ на `main` можно только осознанно
  (`--allow-off-main`), и это ПЕЧАТАЕТСЯ.

## Отказ fail-CLOSED: место приёмки вне принятого кода

Ссылка, чей коммит **не предок `origin/main`**, даёт отказ **код 3**. Причина не
в аккуратности: приёмка на кандидатной ветке мерит систему, которой нет, и
вердикт «критерий не выполнен» в ней ничего не говорит о принятом коде. Именно
этот дефект и был найден на дереве 15.10. Осознанный обход —
`--allow-off-main`, и он печатается строкой.

Существующее дерево НЕ перезаписывается без `--replace`: подменить место
приёмки молча значило бы сменить мерку под идущим замером.

## Коды возврата

* **0** — дерево собрано (либо `--check`: родословная измерена, находок нет).
* **1** — `--check`: родословная измерена, находки НАЗВАНЫ.
* **2** — НЕ ИЗМЕРЕНО / сборка не состоялась: причина названа.
* **3** — ОТКАЗ: коммит ссылки не на `origin/main` (место приёмки вне принятого кода).
* **4** — ОТКАЗ: дерево уже существует, `--replace` не объявлен.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring import acceptance_tree_lineage as lineage  # noqa: E402

#: Путь сборщика ОТ КОРНЯ репозитория — он же попадает в маркер полем `builder`.
#: Собирается из `__file__`, а не вписывается литералом: переименуй файл, и
#: литерал начал бы называть несуществующий путь ровно тем способом, который
#: этот сборщик и чинит.
BUILDER_REL = str(Path(__file__).resolve().relative_to(_REPO_ROOT))

#: Каталоги поверхностей владельца. Объявление владельца (ADR-509): §49 требует
#: и их, и живых артефактов, а вместе они не сходятся ни в одном рабочем дереве.
SURFACE_DIRS = ("landing/src", "spa_core/telegram", "scripts")

#: Версия формы маркера. Прибор родословной читает поля по именам и терпит
#: отсутствие `builder` (маркер v1 его не знал) — поэтому версия и нужна.
MARKER_VERSION = 2


class Refused(Exception):
    """Отказ с названной причиной и кодом возврата."""

    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _git(repo: Path, *args: str, timeout: float = 120.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"git не позван: {exc}"
    return proc.returncode, (proc.stdout or "").strip()


def resolve_ref(repo: Path, ref: str) -> str:
    code, sha = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if code != 0 or not sha:
        raise Refused(2, f"ссылка {ref!r} не разрешается в {repo}: "
                         f"{sha or 'git молчит'}")
    return sha


def check_on_main(repo: Path, sha: str, *, main_ref: str,
                  allow_off_main: bool) -> dict:
    """Предок ли коммит принятой ветки. Три исхода, и они различимы (инв. #17).

    ``unmeasured`` здесь НЕ пропускает сборку: «не смогли спросить» это не
    «ответ да». Обход тот же (`--allow-off-main`), но причина в печати другая.

    **Первым спрашивается, способен ли клон отвечать вообще.** Усечённый клон
    зовёт предка «не предком» молча (замер #1031: прод-клон держит 252 коммита
    из 28 011), и без этой двери отказ код 3 срабатывал бы на верной ссылке —
    то есть гейт запрещал бы сборку тем надёжнее, чем беднее своя история.
    Мерка усечённости НЕ копируется: её держит прибор родословной.
    """
    completeness = lineage.history_completeness(repo)
    if completeness["state"] != "complete":
        raise Refused(2, (
            f"НЕ ИЗМЕРЕНО: происхождение коммита в {repo} не спросить — "
            f"{completeness.get('reason')}. Выдать это за «коммит на {main_ref}» "
            f"нельзя; спроси ПОЛНЫЙ клон через `--repo-root` (например "
            f"{lineage.MIRROR_DEFAULT})"))
    code, main_sha = _git(repo, "rev-parse", "--verify", f"{main_ref}^{{commit}}")
    if code != 0 or not main_sha:
        verdict: dict = {"state": "unmeasured", "main_ref": main_ref,
                   "reason": f"ссылка {main_ref!r} не разрешается: "
                             f"{main_sha or 'git молчит'}"}
    else:
        ancestor, _ = _git(repo, "merge-base", "--is-ancestor", sha, main_sha)
        verdict = {"state": "on_main" if ancestor == 0 else "off_main",
                   "main_ref": main_ref, "main_sha": main_sha,
                   "refs_containing": lineage._refs_containing(repo, sha),
                   "behind": lineage._count(repo, f"{sha}..{main_sha}"),
                   "ahead": lineage._count(repo, f"{main_sha}..{sha}")}
    if verdict["state"] == "on_main":
        return verdict
    detail = (f"коммит {sha[:9]} — состояние {verdict['state']} относительно "
              f"{main_ref}: {verdict.get('reason') or ''}"
              f"позади {verdict.get('behind')}, впереди {verdict.get('ahead')}, "
              f"содержат его {verdict.get('refs_containing') or 'НИ ОДНА ссылка'}")
    if not allow_off_main:
        raise Refused(3, (
            f"ОТКАЗ: место приёмки §49 собирается ВНЕ принятого кода. {detail}. "
            f"Приёмка на невлитой ветке мерит систему, которой нет: вердикт "
            f"«критерий не выполнен» в таком дереве не говорит о принятом коде "
            f"ничего. Осознанный обход — `--allow-off-main`"))
    print(f"⚠️  ОБХОД --allow-off-main: {detail}", file=sys.stderr)
    verdict["bypassed"] = True
    return verdict


def _export_tree(repo: Path, sha: str, dest: Path) -> None:
    """Чистое дерево коммита в `dest`. Рабочее состояние репозитория не читается.

    `git archive` берёт содержимое ИЗ ОБЪЕКТОВ, поэтому незакоммиченные правки,
    сборочный мусор и чужие worktree-остатки в дерево приёмки не попадают — а
    вместе с ними не попадает и класс «дерево держит байты, которых никто не
    писал» (`.claude/rules/deployment.md`, § про окно мутационного прибора).
    """
    dest.mkdir(parents=True, exist_ok=True)
    try:
        archive = subprocess.Popen(
            ["git", "-C", str(repo), "archive", "--format=tar", sha],
            stdout=subprocess.PIPE)
        untar = subprocess.Popen(["tar", "-x", "-C", str(dest)],
                                 stdin=archive.stdout)
        if archive.stdout is not None:
            archive.stdout.close()
        untar.communicate()
        archive.wait()
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused(2, f"выгрузка дерева {sha[:9]} не состоялась: {exc}") from exc
    if archive.returncode != 0 or untar.returncode != 0:
        raise Refused(2, (f"выгрузка дерева {sha[:9]} вернула коды "
                          f"archive={archive.returncode} tar={untar.returncode}"))


def _link_live_data(dest: Path, live_data: Path) -> None:
    """`data` — ССЫЛКА, не копия (см. шапку, п. 2)."""
    if not live_data.exists():
        raise Refused(2, f"живого каталога данных нет: {live_data}. Подставить "
                         f"вместо него копию значило бы завести второй, молча "
                         f"устаревающий источник")
    target = dest / "data"
    if target.is_symlink() or target.exists():
        if target.is_symlink() or target.is_file():
            target.unlink()
        else:
            shutil.rmtree(target)
    target.symlink_to(live_data, target_is_directory=True)


def _freeze(dest: Path) -> int:
    """Снять право записи со всего дерева. Возвращает число изменённых путей.

    Сама ссылка `data` не трогается: `chmod` по ссылке на macOS меняет права
    ЦЕЛИ, то есть живого каталога данных — а это прод-состояние, и трогать его
    сборщик права не имеет.
    """
    touched = 0
    strip = ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    for root, dirs, files in os.walk(dest, topdown=False):
        for name in list(files) + list(dirs):
            path = Path(root) / name
            if path.is_symlink():
                continue
            try:
                mode = path.stat().st_mode
                path.chmod(stat.S_IMODE(mode) & strip)
                touched += 1
            except OSError:
                continue
    try:
        dest.chmod(stat.S_IMODE(dest.stat().st_mode) & strip)
        touched += 1
    except OSError:
        pass
    return touched


def build(repo_root: str | Path, dest: str | Path, *, ref: str = lineage.REF_DEFAULT,
          live_data: Optional[str | Path] = None, main_ref: str = lineage.REF_DEFAULT,
          allow_off_main: bool = False, replace: bool = False,
          freeze: bool = True, now=None) -> dict:
    """Собрать дерево-приёмку и вернуть записанный маркер."""
    repo = Path(repo_root).resolve()
    dest = Path(dest)
    live = Path(live_data).resolve() if live_data else (repo / "data")

    if dest.exists() and not replace:
        raise Refused(4, (
            f"ОТКАЗ: дерево {dest} уже существует. Подменить место приёмки молча "
            f"значило бы сменить мерку под идущим замером — объяви `--replace`"))

    sha = resolve_ref(repo, ref)
    on_main = check_on_main(repo, sha, main_ref=main_ref,
                            allow_off_main=allow_off_main)

    staging = Path(tempfile.mkdtemp(prefix="acceptance_tree_", dir=str(dest.parent)))
    try:
        _export_tree(repo, sha, staging)
        _link_live_data(staging, live)
        marker = {
            "version": MARKER_VERSION,
            "built_at": _stamp(now),
            "builder": BUILDER_REL,
            "ref": ref,
            "commit": sha,
            "source_repo": str(repo),
            "live_data": str(live),
            "read_only": bool(freeze),
            "surface_dirs": list(SURFACE_DIRS),
            "lineage_at_build": on_main,
            "note": (f"дерево-приёмка §49 «Portfolio CIO» (ADR-509, решение "
                     f"владельца, вариант 1). Только для чтения. `data` — ССЫЛКА "
                     f"на живой каталог, не копия. Пересобирать "
                     f"`{BUILDER_REL}`, руками не править. Родословную "
                     f"спрашивать `{BUILDER_REL} --check <дерево>`"),
        }
        (staging / lineage.MARKER_NAME).write_text(
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        if freeze:
            _freeze(staging)
        if dest.exists():
            _retire(dest)
        staging.replace(dest)
    except Exception:
        _retire(staging)
        raise
    return marker


def _retire(path: Path) -> None:
    """Убрать дерево, с которого сначала снят запрет записи.

    Без возврата права записи `shutil.rmtree` упирается в собственный `chmod
    a-w` сборщика и падает на полпути, оставив половину дерева — то есть
    состояние, в котором маркер есть, а кода нет.
    """
    for root, dirs, files in os.walk(path):
        for name in list(dirs) + list(files):
            target = Path(root) / name
            if target.is_symlink():
                continue
            try:
                target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
            except OSError:
                continue
    try:
        path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


def _stamp(now=None) -> str:
    moment = now if now is not None else dt.datetime.now(dt.timezone.utc)
    return moment.isoformat()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=str(_REPO_ROOT),
                    help="репозиторий-источник (умолчание — своё дерево)")
    ap.add_argument("--dest", default=lineage.ACCEPTANCE_TREE_DEFAULT,
                    help="куда собрать дерево-приёмку")
    ap.add_argument("--ref", default=lineage.REF_DEFAULT,
                    help="ссылка, из которой берётся код")
    ap.add_argument("--main-ref", default=lineage.REF_DEFAULT,
                    help="принятая ветка, относительно которой судится родословная")
    ap.add_argument("--live-data", default=None,
                    help="живой каталог данных (умолчание — <repo-root>/data)")
    ap.add_argument("--allow-off-main", action="store_true",
                    help="осознанно собрать дерево вне принятого кода (ПЕЧАТАЕТСЯ)")
    ap.add_argument("--replace", action="store_true",
                    help="заменить существующее дерево")
    ap.add_argument("--no-freeze", action="store_true",
                    help="не снимать право записи (только для сцен тестов)")
    ap.add_argument("--check", nargs="?", const=lineage.ACCEPTANCE_TREE_DEFAULT,
                    default=None, metavar="ДЕРЕВО",
                    help="НЕ собирать, а спросить родословную уже собранного "
                         "дерева (мерка — у прибора, второй копии нет)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    from spa_core.utils.live_paths import refuse_if_sandbox_leaks  # ADR-1000: дверь песочницы, транш 1
    refuse_if_sandbox_leaks(args.repo_root, who="build_acceptance_tree")

    if args.check is not None:
        # Мерка НЕ копируется: её держит прибор родословной. Вторая копия
        # разошлась бы с ним молча (ADR-220), и сборщик начал бы отвечать о
        # дереве иначе, чем шаг 0-офис.
        try:
            doc = lineage.measure(args.repo_root, trees=[args.check],
                                  ref=args.main_ref)
        except lineage.Unmeasured as exc:
            doc = {"status": "UNMEASURED", "reason": str(exc)}
        if args.json:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
        else:
            for line in lineage.report(doc):
                print(line)
        if str(doc.get("status")) != "OK":
            return 2
        return 1 if int(doc.get("findings") or 0) else 0

    try:
        marker = build(args.repo_root, args.dest, ref=args.ref,
                       live_data=args.live_data, main_ref=args.main_ref,
                       allow_off_main=args.allow_off_main,
                       replace=args.replace, freeze=not args.no_freeze)
    except Refused as exc:
        print(exc.reason, file=sys.stderr)
        return exc.code
    if args.json:
        print(json.dumps(marker, ensure_ascii=False, indent=2))
    else:
        print(f"дерево-приёмка §49 собрано → {args.dest}")
        print(f"  ссылка {marker['ref']} → коммит {marker['commit'][:9]} "
              f"({marker['lineage_at_build'].get('state')})")
        print(f"  `data` → {marker['live_data']} (ССЫЛКА, не копия)")
        print(f"  только для чтения: {marker['read_only']}")
        print(f"  родословную спрашивать: python3 {BUILDER_REL} "
              f"--check {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
