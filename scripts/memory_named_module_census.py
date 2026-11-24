#!/usr/bin/env python3
"""scripts/memory_named_module_census.py — ЗАПИСЬ ПАМЯТИ НАЗЫВАЕТ МОДУЛЬ, КОТОРОГО НА `origin/main` НЕТ.

Предмет
-------
Записи файловой памяти сессии (`<project>/memory/*.md`) грузятся в КАЖДУЮ сессию как фон.
Запись, называющая модуль Python, которого на `origin/main` нет, говорит сессии «класс уже
измерен прибором» — и сессия его не мерит. Это не опечатка в прозе: это ЛОЖНОЕ УТВЕРЖДЕНИЕ
О СОСТОЯНИИ МИРА, прочитанное до первой строки работы.

Замер 2026-11-24 (цикл #1230), из которого прибор и написан — ДВА независимых члена:

* `orphaned-worktree-recovery.md` называет `spa_core/monitoring/undelivered_work_census.py`
  («цикл #706, 27.09, ADR-482», артефакт, SLO 12 ч, ступень моста, поимённая ветвь шага
  0-офис) — на `origin/main` НЕТ ни модуля, ни ADR-482, ни ОДНОГО упоминания имени. То есть
  прибор, которому записка поручает мерить ровно класс осиротевшей недоставленной работы,
  сам есть осиротевшая недоставленная работа — 58 дней;
* запись про дверь заказа контрольного прогона называла ADR-1083 доставленным циклом #1229 —
  на `origin/main` не было ни ADR, ни флага `--order-run` (доставил #1230, перемерив байты).

Почему ни один сторож этого не говорит
--------------------------------------
Каталог памяти лежит ВНЕ репозитория и ВНЕ дерева доставки: его не видит ни пушер (он судит
уезжающие байты), ни храповик сторожей-сирот (он перечисляет каталоги репозитория), ни офис
(он читает объявленные артефакты). Утверждение памяти не уезжает никуда и поэтому не судится
ничем.

Три исхода различимы (инв. #17)
-------------------------------
`exists` — модуль назван и он на `origin/main` есть ·
`absent` — НАХОДКА: назван и его нет ·
`unmeasured` — с НАЗВАННОЙ причиной (каталог памяти не прочитан · ссылка не прочитана ·
запись не декодируется). Непрочитанная ссылка НЕ даёт пустого набора: пустой набор объявил
бы находкой КАЖДУЮ запись, то есть ответил бы вместо «не измерено».

Коды возврата: **0** находок нет · **1** находки НАЗВАНЫ · **2** НЕ ИЗМЕРЕНО с причиной.

Что прибор НЕ судит
-------------------
* **Осмысленность** утверждения при существующем модуле: запись, называющая живой модуль и
  врущая о его поведении, через прибор пройдёт. Это следующий вопрос, и мерить его нечем,
  кроме независимого читателя.
* **Не-Python** адреса (`data/*`, `docs/37`, дашборды): `data/` в `.gitignore` по построению,
  поэтому «нет на origin» там НЕ значит «не существует», а короткие формы вида `docs/37` —
  сокращения прозы, а не пути. Спрашивать у них существование значило бы выдумать находку.
  Ось сужена НАМЕРЕННО до того, что объявило себя файлом Python: такой путь git-tracked по
  построению, и вопрос о нём корректен.
* **Заполнитель прозы** (`scripts/X.py`, `spa_core/tests/test_x.py`) находкой не считается —
  но и МОЛЧА не отбрасывается: их число ПЕЧАТАЕТСЯ отдельной строкой. Молчаливый отсев дал бы
  правило, под которым настоящая находка однажды спрячется.
* **Объявленное отсутствие** (`ABSENT-OK: <причина>` на ТОЙ ЖЕ строке) находкой не считается:
  запись вправе НАМЕРЕННО называть модуль, которого нет, — иллюстрация команды про удалённый
  файл, снятое притязание «прибор мерит». Образец формы — `# FROZEN-DATE-OK: <причина>` из
  `.claude/rules/deployment.md`: решение на протоколе, а не недосмотр. ПРИЧИНА обязательна, а
  объявление действует НА СВОЕЙ СТРОКЕ: пометка в шапке спрятала бы соседа по записи. Число
  объявленных отсутствий ПЕЧАТАЕТСЯ — иначе объявление стало бы тихой базой (инв. #16).

Усечённый клон на ЭТОТ вопрос отвечать СПОСОБЕН
-----------------------------------------------
`.claude/rules/deployment.md` § поправка #1031 запрещает верить усечённому клону в вопросах об
ИСТОРИИ. Здесь вопрос о ВЕРШИНЕ («есть ли путь в дереве `origin/main`»), а дерево вершины в
усечённом клоне присутствует целиком — поэтому ответ законен, и глубина клона ПЕЧАТАЕТСЯ
строкой, чтобы читатель видел, о чём ему ответили. Вопрос «существовал ли путь КОГДА-НИБУДЬ»
этим прибором НЕ задаётся: на него усечённый клон ответить не может.

Храповика у класса НЕТ намеренно
--------------------------------
Население узкое (замер #1230: **9** записей на **11** модулей из 916 записей), а база с
десятками ложных срабатываний учит дописывать в неё — тот же выбор и та же причина, что у
личности процесса и у имени ветки (`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Sequence, Tuple

#: Умолчание каталога памяти — ПЕЧАТАЕТСЯ, а названный нечитаемый каталог даёт код 2
#: (урок ADR-933: нечитаемое названное дерево — отказ, не молчаливый возврат к своему).
DEFAULT_MEMORY_DIR = os.path.expanduser(
    "~/.claude/projects/-Users-yuriikulieshov-Documents-SPA-Claude/memory"
)

#: Объявленная форма адреса: путь, объявивший себя файлом Python в КОДОВЫХ каталогах.
#: Такой путь git-tracked по построению, поэтому «нет на origin» о нём есть ответ, а не шум.
NAMED_MODULE = re.compile(r"(?<![\w/.-])((?:scripts|spa_core)/[\w./-]+\.py)")

#: Заполнители прозы. Их число ПЕЧАТАЕТСЯ, а не глотается молча.
PLACEHOLDER = re.compile(
    r"(?:^|/)(?:[a-zA-Z]|x|X|NNN|foo|bar|test_x|test_X)\.py$|NNN|<|>|\{|\*"
)

#: ОБЪЯВЛЕНИЕ ОТСУТСТВИЯ на строке, образец — `# FROZEN-DATE-OK: <причина>` из
#: `.claude/rules/deployment.md`: запись вправе НАМЕРЕННО называть модуль, которого нет
#: (иллюстрация команды про удалённый файл, снятое притязание), и тогда это решение на
#: протоколе, а не недосмотр. ПРИЧИНА — часть объявления: «и так понятно» причиной не является.
#: Объявление действует НА СВОЕЙ СТРОКЕ, а не на всю запись: иначе одна пометка в шапке
#: спрятала бы соседа — дословно дефект, который ловит мутация M07.
ABSENT_DECLARED = re.compile(r"ABSENT-OK:[ \t]*(\S)")

OUT_EXISTS = "exists"
OUT_ABSENT = "absent"
OUT_UNMEASURED = "unmeasured"

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_UNMEASURED = 2


def named_modules(text: str) -> Tuple[List[str], List[str], List[str]]:
    """Адреса, которые запись НАЗЫВАЕТ: (предмет, заполнители, объявленные отсутствующими).

    Возвращает ТРИ списка, а не один с отсевом: и заполнитель, и объявленное отсутствие
    обязаны быть СОСЧИТАНЫ, иначе молчаливый отсев однажды спрячет настоящую находку.
    Разбор ПОСТРОЧНЫЙ: объявление `ABSENT-OK:` действует на своей строке и не вправе
    утащить за собой соседа по записи.
    """
    subject: List[str] = []
    filler: List[str] = []
    declared: List[str] = []
    for line in text.split("\n"):
        line_declares = bool(ABSENT_DECLARED.search(line))
        for hit in sorted(set(NAMED_MODULE.findall(line))):
            if PLACEHOLDER.search(hit):
                if hit not in filler:
                    filler.append(hit)
            elif line_declares:
                if hit not in declared:
                    declared.append(hit)
            elif hit not in subject:
                subject.append(hit)
    # объявленное отсутствие предметом не является даже тогда, когда тот же путь назван
    # где-то ещё БЕЗ объявления: решение на протоколе принято у строки, а не у записи
    return sorted(set(subject) - set(declared)), sorted(filler), sorted(declared)


def tracked_paths(repo_root: str, ref: str) -> Tuple[Optional[frozenset], Optional[str]]:
    """Набор путей дерева `ref`. ОТКАЗ читается как НЕ ИЗМЕРЕНО, а не как пустой набор."""
    try:
        done = subprocess.run(
            ["git", "-C", repo_root, "ls-tree", "-r", "--name-only", ref],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git не запустился: {exc}"
    if done.returncode != 0:
        return None, (f"`git ls-tree {ref}` вернул код {done.returncode}: "
                      f"{(done.stderr or '').strip()[:200]}")
    paths = frozenset(p for p in done.stdout.split("\n") if p)
    if not paths:
        # Пустой набор НЕ выдаётся за ответ: он объявил бы находкой каждую запись.
        return None, f"дерево `{ref}` прочитано ПУСТЫМ — ответ о нём не выдаётся"
    return paths, None


def clone_depth(repo_root: str) -> str:
    """Глубина клона — ПЕЧАТАЕТСЯ, чтобы читатель видел, о чьём дереве ему ответили."""
    try:
        done = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "--is-shallow-repository"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"НЕ ИЗМЕРЕНА ({exc})"
    if done.returncode != 0:
        return "НЕ ИЗМЕРЕНА (git отказал)"
    return "УСЕЧЁН" if done.stdout.strip() == "true" else "полный"


def _read_notes(memory_dir: str) -> Tuple[Optional[List[str]], Optional[str]]:
    if not os.path.isdir(memory_dir):
        return None, f"каталог памяти не прочитан: {memory_dir} — не каталог"
    try:
        names = sorted(n for n in os.listdir(memory_dir) if n.endswith(".md"))
    except OSError as exc:
        return None, f"каталог памяти не прочитан: {exc}"
    if not names:
        return None, f"в {memory_dir} нет ни одной записи `*.md` — ответ не выдаётся"
    return names, None


def build_report(memory_dir: str = DEFAULT_MEMORY_DIR,
                 repo_root: str = ".",
                 ref: str = "origin/main") -> Dict[str, object]:
    """Вердикт о классе. Исходы различимы; «не измерено» всегда с причиной."""
    report: Dict[str, object] = {
        "memory_dir": memory_dir,
        "repo_root": os.path.abspath(repo_root),
        "ref": ref,
        "clone_depth": clone_depth(repo_root),
        "question": "есть ли путь в дереве вершины (НЕ «существовал ли когда-нибудь»)",
        "notes_total": None,
        "notes_naming_a_module": 0,
        "modules_named": 0,
        "placeholders_skipped": 0,
        "declared_absent": 0,
        "findings": [],
        "undecodable": [],
        "outcome": OUT_UNMEASURED,
        "why": None,
    }

    names, why = _read_notes(memory_dir)
    if names is None:
        report["why"] = why
        return report
    report["notes_total"] = len(names)

    paths, why = tracked_paths(repo_root, ref)
    if paths is None:
        report["why"] = why
        return report

    for name in names:
        try:
            with open(os.path.join(memory_dir, name), encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as exc:
            report["undecodable"].append({"note": name, "why": str(exc)})
            continue
        subject, filler, declared = named_modules(text)
        report["placeholders_skipped"] = int(report["placeholders_skipped"]) + len(filler)
        report["declared_absent"] = int(report["declared_absent"]) + len(declared)
        if not subject:
            continue
        report["notes_naming_a_module"] = int(report["notes_naming_a_module"]) + 1
        report["modules_named"] = int(report["modules_named"]) + len(subject)
        missing = [m for m in subject if m not in paths]
        if missing:
            report["findings"].append({"note": name, "absent": missing,
                                       "named": len(subject)})

    if report["undecodable"]:
        report["outcome"] = OUT_UNMEASURED
        report["why"] = (f"{len(report['undecodable'])} запись(ей) не декодируется — "
                         f"вердикт о классе не выдаётся")
        return report
    report["outcome"] = OUT_ABSENT if report["findings"] else OUT_EXISTS
    return report


def exit_code(report: Dict[str, object]) -> int:
    """Код возврата — один на исход, и третий исход НЕ сливается с нулём."""
    outcome = report.get("outcome")
    if outcome == OUT_UNMEASURED:
        return EXIT_UNMEASURED
    if outcome == OUT_ABSENT:
        return EXIT_FINDINGS
    return EXIT_CLEAN


def format_report(report: Dict[str, object]) -> str:
    lines: List[str] = []
    lines.append(
        f"ЗАПИСЬ ПАМЯТИ НАЗЫВАЕТ МОДУЛЬ, КОТОРОГО НЕТ · каталог {report['memory_dir']}"
    )
    lines.append(
        f"  дерево: {report['repo_root']} · ссылка `{report['ref']}` · "
        f"клон {report['clone_depth']} · вопрос: {report['question']}"
    )
    if report["outcome"] == OUT_UNMEASURED:
        lines.append(f"  ⚠️ НЕ ИЗМЕРЕНО: {report['why']}")
        for row in report["undecodable"]:
            lines.append(f"     · {row['note']}: {row['why']}")
        return "\n".join(lines)
    lines.append(
        f"  записей всего {report['notes_total']} · называют модуль "
        f"{report['notes_naming_a_module']} · названных модулей {report['modules_named']} · "
        f"заполнителей прозы отброшено {report['placeholders_skipped']} · "
        f"отсутствий ОБЪЯВЛЕНО с причиной {report['declared_absent']} "
        f"(и те, и другие СОСЧИТАНЫ, а не глотнуты)"
    )
    findings = report["findings"]
    if not findings:
        lines.append("  ✅ находок нет: каждый названный модуль БЕЗ объявления отсутствия есть в дереве вершины")
        return "\n".join(lines)
    absent_total = sum(len(f["absent"]) for f in findings)
    lines.append(
        f"  ❌ НАХОДКИ: {len(findings)} запись(ей) называют {absent_total} отсутствующий(х) модуль(ей)"
    )
    for row in findings:
        lines.append(f"     · {row['note']} → {', '.join(row['absent'])}")
    lines.append("  Починка — у ЗАПИСИ: назвать то, что есть, либо доставить то, что названо.")
    lines.append("  Дописывать исключения ЗАПРЕЩЕНО (инв. #16): храповика у класса нет намеренно.")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--memory-dir", default=DEFAULT_MEMORY_DIR,
                    help="каталог файловой памяти (умолчание ПЕЧАТАЕТСЯ; "
                         "названный нечитаемый каталог даёт код 2)")
    ap.add_argument("--repo-root", default=".", help="дерево, у которого спрашиваем вершину")
    ap.add_argument("--ref", default="origin/main", help="ссылка на вершину")
    ap.add_argument("--json", action="store_true", help="машинный вердикт")
    args = ap.parse_args(argv)

    if args.memory_dir == DEFAULT_MEMORY_DIR:
        print(f"[умолчание] каталог памяти не назван входом — беру {DEFAULT_MEMORY_DIR}",
              file=sys.stderr)

    report = build_report(args.memory_dir, args.repo_root, args.ref)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_report(report))
    return exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
