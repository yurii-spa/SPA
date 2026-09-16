#!/usr/bin/env python3
"""Правка свода правил обязана нести запись в журнале — и это проверяется, а не обещается.

Решение владельца 16.09. Агенту разрешено самому коммитить и пушить правки собственных
инструкций (`CLAUDE.md`, `.claude/rules/*.md`) — **при условии**, что та же правка несёт
строку в `docs/journal/<неделя>.md`: что изменено и почему.

**Почему условие не может жить прозой в списке разрешений.** Список разрешений читается,
а не исполняется: фраза «diff трогает только эти файлы» ничего не проверяет. Условие,
которое некому проверить, держится на внимательности — а именно она в этом проекте по
этому месту отказывала ДВАЖДЫ:

* инвариант #17 пропал из `CLAUDE.md` и его не было **16 суток** (ADR-344): правка легла
  поверх устаревшей копии, унесла пункт, и никто не заметил;
* раздел «личность процесса» исчез из `.claude/rules/deployment.md` на **шесть дней** тем
  же способом (восстановлен сверкой с историей файла, а не по памяти).

Оба раза файл менялся БЕЗ СЛЕДА. Журнальная строка и есть след: она не мешает правке, но
делает её видимой тому, кто будет читать историю.

## Что меряется

Из набора изменённых файлов:

* есть ли среди них ИНСТРУКЦИЯ (`CLAUDE.md` либо `.claude/rules/*.md`);
* есть ли среди них ЖУРНАЛ (`docs/journal/*.md`) — и **добавлены ли в него строки**.

Пустой журнальный файл в наборе не считается: «файл в коммите» и «в журнале что-то
написано» — разные факты, и первый легко получить, ничего не написав.

## Три исхода (инв. #17)

| код | что значит |
|---|---|
| 0 | инструкции не тронуты, либо тронуты и журнал несёт добавленные строки |
| 1 | инструкция изменена БЕЗ записи в журнале — отказ с названными файлами |
| 2 | **НЕ ИЗМЕРЕНО**: не git-дерево, `git` недоступен, диф не прочитан |

Код 2 не выдаётся за успех намеренно: «не смогли проверить» и «проверено, чисто» — разные
ответы, и склеивать их значило бы воспроизвести ровно тот дефект, против которого написано.

Запуск:

    python3 scripts/check_rules_change_is_journalled.py            # индекс (pre-commit)
    python3 scripts/check_rules_change_is_journalled.py --files A B  # явный набор
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

#: Файлы, которые и есть свод правил агента.
CONSTITUTION = "CLAUDE.md"
RULES_DIR = ".claude/rules/"
RULES_SUFFIX = ".md"

#: Где живёт след.
JOURNAL_DIR = "docs/journal/"

EXIT_OK, EXIT_REFUSED, EXIT_NOT_MEASURED = 0, 1, 2


class NotMeasured(RuntimeError):
    """Проверка не состоялась; причина обязана быть названа."""


def _norm(path: str) -> str:
    """Путь от корня репозитория, без ведущего `./`.

    ⚠️ НЕ `lstrip("./")`: это НАБОР СИМВОЛОВ, а не префикс. На `.claude/rules/x.md`
    он съедает ведущую точку, путь перестаёт начинаться с `.claude/`, и ВСЕ правила
    областей молча выпадают из-под проверки — ловил собственным замером по каждому
    случаю, а не на счастливом пути (16.09).
    """
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def is_instruction(path: str) -> bool:
    """Инструкция агента: конституция В КОРНЕ либо правило области."""
    p = _norm(path)
    return p == CONSTITUTION or (p.startswith(RULES_DIR) and p.endswith(RULES_SUFFIX))


def is_journal(path: str) -> bool:
    p = _norm(path)
    return p.startswith(JOURNAL_DIR) and p.endswith(".md")


def _git(args: list[str], cwd: Path) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                             text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"git не запустился ({exc})") from exc
    if out.returncode != 0:
        raise NotMeasured(f"git {' '.join(args)} → код {out.returncode}: "
                          f"{out.stderr.strip()[:200]}")
    return out.stdout


def staged_files(repo: Path) -> list[str]:
    """Файлы в индексе. Не git-дерево ⇒ НЕ ИЗМЕРЕНО, а не «пусто»."""
    return [l for l in _git(["diff", "--cached", "--name-only"], repo).splitlines() if l.strip()]


def journal_added_lines(repo: Path, paths: list[str]) -> int:
    """Сколько строк ДОБАВЛЕНО в журнальные файлы набора.

    Считаются именно добавления: файл, попавший в коммит без единой новой строки,
    следа не оставляет — он лишь выглядит как след.
    """
    journals = [p for p in paths if is_journal(p)]
    if not journals:
        return 0
    added = 0
    for j in journals:
        diff = _git(["diff", "--cached", "--unified=0", "--", j], repo)
        added += sum(1 for l in diff.splitlines()
                     if l.startswith("+") and not l.startswith("+++"))
    return added


def verdict(paths: list[str], journal_added: int) -> tuple[int, str]:
    """Вердикт по набору файлов и числу добавленных журнальных строк."""
    touched = sorted(p for p in paths if is_instruction(p))
    if not touched:
        return EXIT_OK, "свод правил не тронут — проверять нечего"
    if journal_added > 0:
        return EXIT_OK, (f"инструкции изменены ({', '.join(touched)}) и след есть: "
                         f"в журнал добавлено строк — {journal_added}")
    return EXIT_REFUSED, (
        f"изменены инструкции агента без записи в журнал: {', '.join(touched)}.\n"
        f"Разрешение владельца (16.09) даёт правку СВОДА ПРАВИЛ вместе со следом, а не "
        f"вместо него: допиши в docs/journal/<неделя>.md, что изменено и почему, и включи "
        f"журнал в тот же коммит.\n"
        f"Почему так: инвариант #17 пропал из CLAUDE.md на 16 суток, а раздел "
        f"deployment.md — на шесть дней; оба раза файл менялся БЕЗ СЛЕДА, и никто не "
        f"заметил.")


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--files", nargs="*", default=None,
                    help="явный набор файлов (умолчание — индекс git)")
    ap.add_argument("--repo", default=None, help="корень репозитория")
    args = ap.parse_args(argv)
    repo = Path(args.repo or os.environ.get("SPA_REPO") or Path(__file__).resolve().parents[1])

    try:
        if args.files is None:
            paths = staged_files(repo)
            added = journal_added_lines(repo, paths)
        else:
            paths = list(args.files)
            # Явный набор: считать добавленные строки нечем — спрашиваем индекс, а если
            # его нет, честно говорим «не измерено», а не подставляем ноль.
            added = journal_added_lines(repo, paths) if any(is_journal(p) for p in paths) else 0
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО — {exc}", file=sys.stderr)
        return EXIT_NOT_MEASURED

    code, text = verdict(paths, added)
    print(("✅ " if code == EXIT_OK else "❌ ") + text,
          file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
