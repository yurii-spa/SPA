#!/usr/bin/env python3
"""Производитель ЗАПИСИ для критерия §49 `No regression` приказа «Portfolio CIO».

Заказ **G673 п. 1** (цикл #810): критерий §49 `No regression` измеряется ТОЛЬКО
junit-записью прогона, а записи прогона на хосте **не держит никто**. Перепись
(:mod:`spa_core.monitoring.no_regression_census`) записи не производит НАМЕРЕННО —
она прибор, запись ей подают входом. Производителя не было ни одного, и замер
17.10 показал цену этого: артефакт `data/no_regression_census.json` написан 28.09,
возраст **448.9 ч** при пределе пробы **192 ч** ⇒ критерий владельца стоял
`unmeasured`. Он не краснел и не зеленел — он молча перестал отвечать.

## Что делает этот скрипт и чего он НЕ делает

| делает | НЕ делает |
|---|---|
| считает население трёх объявленных поверхностей (перепись, разбором дерева) | не расширяет и не сужает население — это предмет №2 границы ADR-285 |
| гоняет pytest РОВНО по этим файлам с `--junitxml` | не гоняет предписанный прогон четырёх каталогов и не выдаёт себя за него |
| ХРАНИТ запись в дереве, которое ПЕРЕЖИВЁТ прогон (`--records-root`, умолчание — боевое дерево) | ничего не удаляет без явного `--keep N` |
| отдаёт запись переписи и пишет её отчёт | не считает вердикт сам — мерка одна, и она у переписи |

**Вердикт этого прогона отвечает на вопрос владельца и только на него:**
«проходят ли существующие risk/security/architecture-тесты». Он НЕ утверждает,
что зелен весь предписанный набор (`CLAUDE.md`, «Все тесты») — у того вердикта
свой читатель и на сегодня он измеряется в CI.

## Третий исход — у каждого отказа (инв. #17)

«Не измерено» никогда не выдаётся ни за зелень, ни за находку:

* дерево — ПРОД (`spa_core.utils.live_paths.DEFAULT_LIVE_ROOT`) ⇒ отказ ДО запуска.
  Тесты населения пишут в `data/` своего дерева; прогнать их в боевом дереве значило
  бы ровно то, что запрещает `.claude/rules/deployment.md` п. 4. Осознанный обход —
  `--allow-prod-tree`, и он печатается в отчёте;
* `pytest` не запускается (нет модуля, упал на сборке) ⇒ НЕ ИЗМЕРЕНО с кодом возврата
  и хвостом вывода. Отдельный вопрос отдельной пробой: «инструмент есть?» не
  отвечается кодом рабочего прогона (`.claude/rules/deployment.md`, урок `pyflakes`);
* записи после прогона нет или в ней ноль случаев ⇒ НЕ ИЗМЕРЕНО. Это НЕ редкость:
  `--timeout-method=thread` зовёт `os._exit(1)` и снимает сессию, тогда junit-файла
  не остаётся вовсе (ADR-474). Пустая запись не записывается как «всё прошло»;
* перепись не измерила (население не разобрано, поверхность пуста) ⇒ её собственная
  причина, дословно.

Код возврата говорит о СОСТОЯНИИ КРИТЕРИЯ, а не об успехе скрипта:
**0** — измерено, регрессии нет · **1** — измерено, поломки НАЗВАНЫ (находка;
гасить правкой теста запрещено, инв. #16) · **2** — НЕ ИЗМЕРЕНО с названной причиной.

## Такт решает ФАЙЛ, а не расписание

`--if-due` сверяет возраст действующего артефакта с `--max-age-h` (по умолчанию
120 ч — ниже предела пробы 192 ч, чтобы критерий не успевал протухнуть между
прогонами). Не срок ⇒ скрипт НИЧЕГО не перезапускает и печатает вердикт ПРЕЖНЕГО
замера вместе с его возрастом, чтобы «0» нельзя было прочитать как «я только что
померил».

Только stdlib (инв. #4). Прибор не правит ни одного теста (инв. #16), не трогает
RiskPolicy, стоп-кран и живой трек. LLM запрещён.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET  # stdlib-only (инв. #4), как у переписи: запись
# производит наш же pytest в этом же процессе-потомке, внешнего XML здесь нет вовсе.
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Куда складываются записи прогона (относительно каталога хранения).
#: `data/records/` в .gitignore — запись живёт на ХОСТЕ и на origin не уезжает.
RECORDS_REL = Path("data") / "records" / "no_regression"

#: Где хранить записи ПО УМОЛЧАНИЮ — и это НЕ дерево прогона, хотя произведена
#: запись именно там. Прогон обязан идти в ОДНОРАЗОВОМ дереве (см.
#: `_refuse_if_prod_tree`), а одноразовое дерево на то и одноразовое: вместе с ним
#: исчезла бы и запись, то есть ровно то, чего требует заказ G673 п. 1 («записи
#: прогона на хосте не держит никто»), осталось бы невыполненным. Поэтому «где
#: гнать» и «где хранить» — два разных входа: по умолчанию хранилище — боевое
#: дерево (оно переживает любой worktree), и ПИШЕТСЯ туда только XML-запись, а не
#: результат тестов.
DEFAULT_RECORDS_ROOT = Path.home() / "Documents" / "SPA_Claude"

#: Предел возраста действующего артефакта для `--if-due`. Ниже предела пробы
#: (`card_acceptance._NO_REGRESSION_MAX_AGE_H` = 192 ч) НАМЕРЕННО: равные пороги
#: означали бы, что критерий протухает ровно в тот момент, когда наступает срок.
DEFAULT_MAX_AGE_H = 120.0

#: Окружение предписанного прогона. Переменные — часть команды, а не фон:
#: `PYTHONHASHSEED` фиксирует порядок обхода множеств, `SPA_ENV=ci` включает
#: ci-ветки (`CLAUDE.md`, цикл #421). Без них прогон отвечает на СВОЙ вопрос.
RUN_ENV = {"SPA_ENV": "ci", "PYTHONHASHSEED": "0"}

NOT_MEASURED = "unmeasured"


class NotMeasured(RuntimeError):
    """Замер не состоялся. Причина обязана быть названа."""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def artifact_age_hours(repo_root: Path, *, now: datetime | None = None) -> tuple[float | None, str]:
    """Возраст действующего отчёта переписи в часах и ПОЧЕМУ он таков.

    ``None`` — возраст НЕ ИЗМЕРЕН (файла нет, не разобран, нет отметки времени).
    Это не «ноль часов» и не «старый»: третий исход у возраста тоже свой.
    """
    from spa_core.monitoring import no_regression_census as census

    path = repo_root / census.REPORT_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"отчёта переписи нет: {type(exc).__name__}: {exc}"
    except ValueError as exc:
        return None, f"отчёт переписи не разобран: {type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return None, "отчёт переписи не словарь"
    stamp = doc.get("generated_at")
    try:
        made = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None, f"у отчёта нет читаемой отметки времени (generated_at={stamp!r})"
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    age = ((now or datetime.now(timezone.utc)) - made).total_seconds() / 3600.0
    return age, (f"возраст действующего отчёта {age:.1f}ч, вердикт "
                 f"{doc.get('verdict')!r}, измерено={doc.get('measured')!r}")


def population_files(repo_root: Path) -> list[str]:
    """Файлы населения трёх объявленных поверхностей — одной копией у переписи.

    Считает НЕ этот скрипт: своя копия правила принадлежности разошлась бы с
    переписью при первой же правке и дала бы два разных населения у одного
    критерия (класс ADR-522).
    """
    from spa_core.monitoring import no_regression_census as census

    pop = census.population(str(repo_root))
    if pop["roots_absent"]:
        raise NotMeasured("каталог(и) предписанного прогона не найдены: "
                          + ", ".join(pop["roots_absent"]))
    if pop["unparsed"]:
        raise NotMeasured(f"{len(pop['unparsed'])} тест-файл(ов) не разобран(ы): "
                          + ", ".join(u["file"] for u in pop["unparsed"][:5])
                          + " — принадлежность НЕИЗВЕСТНА")
    empty = [name for name, s in pop["surfaces"].items() if not s["files"]]
    if empty:
        raise NotMeasured("население поверхност(и/ей) ПУСТО: " + ", ".join(empty))
    files: list[str] = []
    for surface in pop["surfaces"].values():
        for rel in surface["files"]:
            if rel not in files:
                files.append(rel)
    return files


def _refuse_if_prod_tree(repo_root: Path, *, allow: bool) -> None:
    """Прогон тестов в БОЕВОМ дереве запрещён, и отказ громкий.

    Тесты населения пишут в `data/` того дерева, из которого запущены, а в боевом
    дереве `data/` — это состояние, а не мусор (`.claude/rules/deployment.md` п. 4,
    авария 2026-08-24: 116 файлов откатились на три недели). Поэтому вопрос
    задаётся ДО запуска и ответ на него — отказ, а не предупреждение.
    """
    if allow:
        return
    try:
        from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT
    except Exception as exc:  # noqa: BLE001 — нечем спросить ≠ «можно»
        raise NotMeasured(f"не удалось узнать путь боевого дерева: "
                          f"{type(exc).__name__}: {exc} — прогон НЕ начат") from exc
    try:
        same = repo_root.resolve() == Path(DEFAULT_LIVE_ROOT).resolve()
    except OSError as exc:
        raise NotMeasured(f"путь дерева не разрешился: {type(exc).__name__}: {exc}") from exc
    if same:
        raise NotMeasured(
            f"дерево {repo_root} — БОЕВОЕ ({DEFAULT_LIVE_ROOT}). Тесты населения пишут "
            f"в `data/` своего дерева, а в боевом `data/` — живое состояние "
            f"(.claude/rules/deployment.md п. 4). Гонять население надо из одноразового "
            f"worktree; осознанный обход — --allow-prod-tree")


def run_population(repo_root: Path, files: list[str], record: Path,
                   *, timeout_s: float | None = None) -> dict:
    """Прогнать РОВНО население и оставить junit-запись на хосте.

    Возвращает словарь наблюдений о прогоне (код возврата, число случаев в
    записи, хвост вывода). Запись-пустышка и отсутствие записи — третий исход:
    :class:`NotMeasured`, а не «ноль поломок».
    """
    record.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", *files,
           "-q", "--tb=no", "-p", "no:randomly", f"--junitxml={record}"]
    env = {**os.environ, **RUN_ENV}
    try:
        proc = subprocess.run(cmd, cwd=str(repo_root), env=env, timeout=timeout_s,
                              capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise NotMeasured(f"pytest не запущен: {type(exc).__name__}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise NotMeasured(f"прогон населения снят по сроку {timeout_s}с — вердикта нет "
                          f"ни у одного члена: {exc}") from exc
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-6:])
    if not record.exists():
        raise NotMeasured(
            f"pytest вышел с кодом {proc.returncode}, а junit-записи нет: {record}. "
            f"Так выглядит снятая сессия (ADR-474: --timeout-method=thread зовёт "
            f"os._exit(1)), и это НЕ «все прошли». Хвост вывода: {tail!r}")
    try:
        cases = len(list(ET.parse(record).getroot().iter("testcase")))
    except (OSError, ET.ParseError) as exc:
        raise NotMeasured(f"junit-запись не разобрана: {type(exc).__name__}: {exc}") from exc
    if cases == 0:
        raise NotMeasured(f"в junit-записи {record} ноль случаев — прогон не дал исхода "
                          f"ни одному члену населения (код pytest {proc.returncode})")
    return {"returncode": proc.returncode, "cases_in_record": cases,
            "record": str(record), "tail": tail, "files_requested": len(files)}


def refresh(repo_root: Path, *, if_due: bool = False, max_age_h: float = DEFAULT_MAX_AGE_H,
            junit: list[str] | None = None, allow_prod_tree: bool = False,
            write: bool = True, timeout_s: float | None = None,
            records_root: Path | None = None,
            now: datetime | None = None) -> dict:
    """Обновить отчёт переписи, произведя запись прогона, и вернуть наблюдения."""
    from spa_core.monitoring import no_regression_census as census

    age, why_age = artifact_age_hours(repo_root, now=now)
    out: dict = {"repo_root": str(repo_root), "artifact_age_h": age, "age_reason": why_age,
                 "max_age_h": max_age_h, "ran": False,
                 # Обход отказа «дерево боевое» обязан быть ВИДЕН читателю отчёта: молчаливый
                 # обход превращает отказ в украшение.
                 "allow_prod_tree": bool(allow_prod_tree)}

    if if_due and age is not None and age <= max_age_h:
        # Не срок. Вердикт берётся у ДЕЙСТВУЮЩЕГО отчёта, и его возраст называется
        # вслух: иначе «0» читалось бы как «я только что померил».
        try:
            doc = json.loads((repo_root / census.REPORT_REL).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # отчёт исчез между замером и чтением
            raise NotMeasured(f"возраст отчёта измерен, а сам отчёт не прочитан: "
                              f"{type(exc).__name__}: {exc}") from exc
        out.update({"due": False, "report": doc, "source": "прежний отчёт"})
        return out
    out["due"] = True

    if junit:
        out["source"] = "запись подана входом"
        paths = list(junit)
    else:
        _refuse_if_prod_tree(repo_root, allow=allow_prod_tree)
        files = population_files(repo_root)
        keep_in = Path(records_root) if records_root is not None else DEFAULT_RECORDS_ROOT
        record = keep_in / RECORDS_REL / f"{_stamp()}.xml"
        out["records_root"] = str(keep_in)
        out["run"] = run_population(repo_root, files, record, timeout_s=timeout_s)
        out["ran"] = True
        out["source"] = f"прогон населения ({len(files)} файл(ов)) на этом хосте"
        paths = [str(record)]

    report = census.measure(str(repo_root), junit_paths=paths)
    out["report"] = report
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, str(repo_root / census.REPORT_REL))
        out["written"] = str(repo_root / census.REPORT_REL)
    return out


def prune_records(records_root: Path, keep: int) -> list[str]:
    """Снять все записи, кроме ``keep`` самых свежих. ``keep<=0`` — не снимать ничего.

    Удаление необратимо, поэтому оно НЕ по умолчанию и трогает только файлы
    собственного каталога записей с собственным расширением.
    """
    if keep <= 0:
        return []
    base = Path(records_root) / RECORDS_REL
    if not base.is_dir():
        return []
    found = sorted((p for p in base.glob("*.xml") if p.is_file()),
                   key=lambda p: p.name, reverse=True)
    dropped = []
    for p in found[keep:]:
        p.unlink()
        dropped.append(str(p))
    return dropped


def _lines(out: dict) -> list[str]:
    from spa_core.monitoring import no_regression_census as census

    lines = []
    if out.get("due") is False:
        lines.append(f"не срок: {out['age_reason']} при пределе {out['max_age_h']:.0f}ч — "
                     f"ничего не перезапускалось")
    run = out.get("run")
    if run:
        lines.append(f"[ПРОГОН] населения {run['files_requested']} файл(ов) → "
                     f"{run['cases_in_record']} случа(й/ев) в записи, код pytest "
                     f"{run['returncode']}; запись оставлена на хосте: {run['record']}")
    report = out.get("report") or {}
    lines += census._lines(report) if report else ["отчёта нет"]
    lines.append(f"[ИСТОЧНИК ВЕРДИКТА] {out.get('source')}")
    if out.get("allow_prod_tree"):
        lines.append("[ОБХОД] --allow-prod-tree: отказ «дерево боевое» снят ОСОЗНАННО — "
                     "тесты населения писали в `data/` этого дерева")
    if out.get("written"):
        lines.append(f"[ЗАПИСАНО] {out['written']}")
    return lines


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=str(ROOT))
    ap.add_argument("--if-due", action="store_true",
                    help=f"прогонять только если отчёт старше --max-age-h "
                         f"(по умолчанию {DEFAULT_MAX_AGE_H:.0f}ч)")
    ap.add_argument("--max-age-h", type=float, default=DEFAULT_MAX_AGE_H)
    ap.add_argument("--junit", action="append", default=[],
                    help="взять ГОТОВУЮ запись (например выгрузку CI) вместо прогона")
    ap.add_argument("--allow-prod-tree", action="store_true",
                    help="осознанный обход отказа «дерево боевое»")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--records-root", default=None,
                    help=f"каталог ХРАНЕНИЯ записей (умолчание {DEFAULT_RECORDS_ROOT}) — "
                         f"он переживает одноразовое дерево прогона")
    ap.add_argument("--keep", type=int, default=0,
                    help="оставить N самых свежих записей, остальные снять (0 — не снимать)")
    ap.add_argument("--timeout-s", type=float, default=None,
                    help="предел на весь прогон населения; снятие по сроку = НЕ ИЗМЕРЕНО")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    try:
        out = refresh(repo_root, if_due=args.if_due, max_age_h=args.max_age_h,
                      junit=args.junit, allow_prod_tree=args.allow_prod_tree,
                      write=not args.no_write, timeout_s=args.timeout_s,
                      records_root=Path(args.records_root) if args.records_root else None)
    except NotMeasured as exc:
        print(f"критерий §49 `No regression`: НЕ ИЗМЕРЕНО — {exc}")
        return 2

    for line in _lines(out):
        print(line)
    for path in prune_records(Path(args.records_root) if args.records_root
                              else DEFAULT_RECORDS_ROOT, args.keep):
        print(f"[СНЯТА ЗАПИСЬ] {path}")

    from spa_core.monitoring import no_regression_census as census
    report = out.get("report") or {}
    if not report.get("measured") or report.get("verdict") == census.UNMEASURED:
        return 2
    return 1 if report.get("verdict") == census.REGRESSION else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
