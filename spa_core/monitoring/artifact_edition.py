#!/usr/bin/env python3
"""Чья РЕДАКЦИЯ произвела вывод артефакта: сегодняшняя или уже заменённая.

Офис печатает КАЖДОМУ артефакту возраст (`consume_office_reports._age_line`) и
НЕКОТОРЫМ — смену ПРЕДМЕТА проверки (`_subject_drift`, объявлено у 2 артефактов
из 133). Ни то, ни другое не отвечает на третий вопрос, и именно он решает,
можно ли ДЕЙСТВОВАТЬ по напечатанной находке:

    **тот ли КОД её вынес, который лежит в дереве сегодня?**

Возраст отвечает «когда», предмет — «о чём», и оба молчат о том, что сам
ПРИБОР с тех пор переписан. Артефакт, произведённый до починки своего
производителя, несёт вывод ПРЕЖНЕЙ редакции — и печатается наравне со свежим,
под общим напутствием офиса «красные строки выше = действовать (карточки)».

## Авария, ради которой прибор написан (замер 2026-11-15, цикл #1158)

`data/cio_architecture_constraints.json` произведён **2026-10-29T09:57**
(возраст 414 ч) и несёт CRITICAL об инварианте #3:

    «единственный сторож инварианта #3 (`scripts/lint_llm_forbidden.py`) видит
    ТОЛЬКО импорт SDK … вставить вызов claude в risk/execution/monitoring
    можно, и ни одна проверка не покраснеет»

Утверждение **НЕВЕРНО на сегодняшнем коде**, и неверно в опасную сторону — оно
зовёт закрытую дверь открытой, то есть приглашает «починить» исправного
сторожа. Положительный контроль, снятый этим циклом: дверь-подпроцесс,
подсаженная в `spa_core/risk/`, ловится — `VIOLATION:
spa_core/risk/planted_door.py:6: launches claude via subprocess.run`, код
возврата 1. Производителя (`cio_architecture_constraints.lint_blindness`)
починил **ADR-969** 2026-11-09, на одиннадцать дней ПОЗЖЕ артефакта: до него
замер спрашивал одну дверь сторожа из двух и печатал вывод о СТОРОЖЕ из нуля,
полученного ПО ПОСТРОЕНИЮ (CRITICAL печатался двенадцать циклов подряд).

То есть починка приехала, а напечатанная находка осталась — потому что никто не
спрашивал, какая редакция её вынесла.

**Население класса ИЗМЕРЕНО** (тот же замер, полный клон): из **133**
объявленных артефактов производитель правлен ПОСЛЕ производства у **18**,
не правлен у **110**, и **5** честно НЕ ИЗМЕРЕНЫ. Это не «один испорченный
файл», а класс.

## Почему клон ВЫБИРАЕТСЯ, а не берётся

Вопрос «когда последний раз менялся производитель» задаётся git'у, а
прод-клон `~/Documents/SPA_Claude` (и КАЖДЫЙ его worktree) **УСЕЧЁН** —
`.claude/rules/deployment.md` § поправка #1031, ADR-918. На усечённом графе
`git log -1 <ref> -- <путь>` отвечает **кодом 0 и без предупреждения**, но
отдаёт дату ГРАНИЦЫ усечения вместо настоящей.

Цена измерена этим же циклом: из 133 производителей ответ усечённого клона
расходится с полным у **118**, и почти у всех это одна и та же подставная дата
границы. Приняв её, прибор объявил бы «редакция сменилась» почти про ВЕСЬ
офис — то есть усечение не прячет дефект, а РОЖДАЕТ его, ровно как в ADR-918.

Поэтому клон здесь не берётся, а выбирается ЕДИНСТВЕННОЙ дверью
:func:`acceptance_tree_lineage.pick_lineage_repo`: порядок кандидатов объявлен,
усечённый отвергается с названной причиной, выбор ПЕЧАТАЕТСЯ. Своей копии этого
решения прибор не держит — второе определение «полный ли клон» разошлось бы с
первым молча.

## Три исхода различимы (инв. #17)

* :data:`CURRENT` — производитель не менялся после производства ⇒ вывод о
  сегодняшнем коде, печатать нечего;
* :data:`STALE_EDITION` — производитель правлен ПОСЛЕ ⇒ вывод вынесен ПРЕЖНЕЙ
  редакцией прибора;
* :data:`UNMEASURED` — спросить нечем: клон не способен ответить · у пути нет
  ни одного коммита · момент производства не прочитан. **Ни один из этих
  случаев не есть `CURRENT`**: подставить здесь «актуален» значило бы выдать
  «не измерено» за «сверено», то есть fail-OPEN тише красной строки.

Прибор только ЧИТАЕТ: он не правит артефакты, не перезапускает производителей и
не гасит ни одной напечатанной находки. Он добавляет к находке признак её
редакции — потому что «действовать по ней» и «перемерить её» это разные
следующие шаги, а до сих пор они выглядели одинаково.

**Момент производства артефакта прибор НЕ ЧИТАЕТ сам.** Единица и имя поля
объявлены у офиса (`_TS_FIELD` / `_TS_UNIT`, ADR-513), и заглянуть туда
самостоятельно значило бы завести ВТОРОЙ дом той же величины. Поэтому моменты
приходят ВХОДОМ от вызывающего.
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring.acceptance_tree_lineage import (  # noqa: E402
    MIRROR_DEFAULT,
    Unmeasured,
    pick_lineage_repo,
)

#: Ссылка, у которой спрашивают историю производителя. Рабочее дерево и локальная
#: `main` дрейфуют от origin по построению (пуши идут через API, минуя индекс —
#: `CLAUDE.md`, ADR-152), поэтому вопрос задаётся УДАЛЁННОЙ ветке.
REF_DEFAULT = "origin/main"

CURRENT = "current"
STALE_EDITION = "stale_edition"
UNMEASURED = "unmeasured"


@dataclass(frozen=True)
class Verdict:
    """Ответ о ОДНОМ артефакте. `reason` обязателен у :data:`UNMEASURED`."""

    kind: str
    artifact: str
    producer: str
    produced_at: Optional[dt.datetime] = None
    changed_at: Optional[dt.datetime] = None
    lag_hours: Optional[float] = None
    repo: Optional[str] = None
    reason: Optional[str] = None

    @property
    def stale(self) -> bool:
        return self.kind == STALE_EDITION


@dataclass
class Census:
    """Замер по всему объявленному перечню."""

    verdicts: list[Verdict] = field(default_factory=list)
    repo: Optional[str] = None
    rejected: list[dict] = field(default_factory=list)
    reason: Optional[str] = None

    @property
    def measured(self) -> bool:
        return self.reason is None

    def by_kind(self, kind: str) -> list[Verdict]:
        return [v for v in self.verdicts if v.kind == kind]


def _git(repo: Path, *args: str, timeout: float = 30.0) -> tuple[int, str]:
    """`git` в названном клоне. Возвращает код и ОБРЕЗАННЫЙ stdout.

    Обрезается только хвостовой перевод строки (`rstrip("\\n")`), а не пробелы:
    `.strip()` съедает ведущий пробел первой строки у колоночных форматов, и
    срез по колонке после него врёт (урок `_git` портит колоночный вывод).
    """
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout.rstrip("\n")


def changed_at(repo: Path, producer_rel: str, *,
               ref: str = REF_DEFAULT) -> tuple[Optional[dt.datetime], Optional[str]]:
    """Когда производитель менялся последний раз на `ref`.

    Пустой ответ — это НЕ «не менялся никогда»: так же выглядит и путь, которого
    на ветке нет вовсе, и опечатка в объявлении. Поэтому пустота возвращается
    как названная причина, а не как `None`-дата с молчаливым выводом «актуален».
    """
    code, out = _git(repo, "log", "-1", "--format=%cI", ref, "--", producer_rel)
    if code != 0:
        return None, (f"git не ответил о {producer_rel} на {ref} "
                      f"(код {code}): {out or 'пусто'}")
    if not out:
        return None, (f"у {producer_rel} нет ни одного коммита на {ref} — "
                      f"объявленного производителя на ветке НЕТ, и «не менялся» "
                      f"из этого не следует")
    try:
        stamp = dt.datetime.fromisoformat(out)
    except ValueError:
        return None, f"дата коммита {producer_rel} не разобрана: {out!r}"
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return stamp, None


def verdict(artifact: str, producer: str, *, produced_at: Optional[dt.datetime],
            repo: Path, ref: str = REF_DEFAULT) -> Verdict:
    """Ответ об одном артефакте в УЖЕ ВЫБРАННОМ клоне."""
    if produced_at is None:
        return Verdict(UNMEASURED, artifact, producer, repo=str(repo),
                       reason=("момент производства не прочитан — сказать, чья "
                               "редакция вынесла вывод, нечем"))
    if produced_at.tzinfo is None:
        produced_at = produced_at.replace(tzinfo=dt.timezone.utc)
    stamp, why = changed_at(repo, producer, ref=ref)
    if stamp is None:
        return Verdict(UNMEASURED, artifact, producer, produced_at=produced_at,
                       repo=str(repo), reason=why)
    lag = round((stamp - produced_at).total_seconds() / 3600.0, 2)
    kind = STALE_EDITION if stamp > produced_at else CURRENT
    return Verdict(kind, artifact, producer, produced_at=produced_at,
                   changed_at=stamp, lag_hours=lag, repo=str(repo))


def measure(producers: Mapping[str, str],
            moments: Mapping[str, Optional[dt.datetime]] | Callable[[str], Optional[dt.datetime]],
            *, repos: Optional[Sequence[str]] = None,
            ref: str = REF_DEFAULT) -> Census:
    """Замер по перечню «артефакт → производитель».

    `moments` — момент производства КАЖДОГО артефакта, входом (см. докстринг
    модуля: второй дом величины запрещён). Артефакта нет в `moments` ⇒ это
    :data:`UNMEASURED` с названной причиной, а не пропуск: пропущенная строка
    неотличима от сверенной.

    Ни один клон не способен ответить ⇒ замер НЕ ВЫДАЁТСЯ вовсе (`reason`), а не
    подменяется усечённым: подставная дата границы объявила бы сменившими
    редакцию почти все артефакты.
    """
    candidates = list(repos) if repos is not None else [str(_REPO_ROOT), MIRROR_DEFAULT]
    try:
        repo, rejected = pick_lineage_repo(candidates)
    except Unmeasured as exc:
        return Census(reason=str(exc))

    getter = moments if callable(moments) else moments.get
    out = Census(repo=str(repo), rejected=rejected)
    for artifact, producer in sorted(producers.items()):
        out.verdicts.append(
            verdict(artifact, producer, produced_at=getter(artifact),
                    repo=repo, ref=ref))
    return out


def edition_line(v: Verdict) -> list[str]:
    """Строка(и) офиса об ОДНОМ артефакте. У :data:`CURRENT` — молчание.

    Молчание здесь безопасно и только здесь: «редакция та же» и есть обычное
    положение дел, а печатать его у 110 артефактов из 133 значило бы утопить
    остальные 18 — ровно то, из-за чего CRITICAL об инварианте #3 прожил
    незамеченным двенадцать циклов.
    """
    if v.kind == CURRENT:
        return []
    if v.kind == UNMEASURED:
        return [f"   ⚠️ РЕДАКЦИЯ ПРОИЗВОДИТЕЛЯ НЕ ИЗМЕРЕНА: {v.reason}"]
    return [
        f"   ⏳ ВЫВОД ПРЕЖНЕЙ РЕДАКЦИИ: {v.producer} правлен "
        f"{v.changed_at:%Y-%m-%dT%H:%M}Z — через {v.lag_hours:.1f}ч ПОСЛЕ того, "
        f"как этот артефакт произведён. Находки ниже вынес ПРЕЖНИЙ код.",
        f"   Следующий шаг — ПЕРЕМЕРИТЬ производителем из дерева, а не "
        f"действовать по напечатанному: починка могла уже приехать.",
    ]


def _named_rows(items: Sequence[Verdict], *, kind_label: str,
                max_rows: Optional[int],
                line: Callable[[Verdict], str]) -> list[str]:
    """Имена рода + ОБЪЯВЛЕНИЕ умолчанного остатка.

    Предел строк существует ради читаемости, но «напечатано всё» и
    «напечатана часть» обязаны быть РАЗЛИЧИМЫ (инв. #17): иначе читающий
    получает 12 имён под числом 18 и не узнаёт об этом ниоткуда — ровно так
    заказ G1009 п. 1 потребовал «идти ПОИМЁННО» у прибора, который поимённо
    не называет. Умолчание названо числом И выходом из него; строки «ещё 0»
    нет намеренно — пустое объявление учат пролистывать.

    `max_rows=None` ⇒ предела нет (CLI `--all`).
    """
    shown = list(items) if max_rows is None else list(items)[:max_rows]
    rows = [line(v) for v in shown]
    withheld = len(items) - len(shown)
    if withheld:
        rows.append(
            f"  [УМОЛЧАНО] ещё {withheld} имён рода {kind_label} НЕ напечатано "
            f"(предел строк {max_rows}) — полный перечень: --all")
    return rows


def report(c: Census, max_rows: Optional[int] = 12) -> list[str]:
    """Человекочитаемый свод замера."""
    if not c.measured:
        return [f"РЕДАКЦИЯ ПРОИЗВОДИТЕЛЕЙ НЕ ИЗМЕРЕНА: {c.reason}"]
    stale, unmeasured = c.by_kind(STALE_EDITION), c.by_kind(UNMEASURED)
    lines = [
        f"редакция производителя (клон {c.repo}, ссылка {REF_DEFAULT}):",
        f"  всего артефактов: {len(c.verdicts)}",
        f"  вывод СЕГОДНЯШНЕЙ редакции: {len(c.by_kind(CURRENT))}",
        f"  вывод ПРЕЖНЕЙ редакции: {len(stale)}",
        f"  НЕ ИЗМЕРЕНО: {len(unmeasured)}",
    ]
    for r in c.rejected:
        lines.append(f"  [клон отвергнут] {r.get('repo')} — "
                     f"{r.get('reason', r.get('state'))}")
    lines += _named_rows(
        sorted(stale, key=lambda x: -(x.lag_hours or 0)),
        kind_label="ПРЕЖНЯЯ", max_rows=max_rows,
        line=lambda v: (f"  [ПРЕЖНЯЯ] {v.artifact}: производитель {v.producer} "
                        f"правлен через {v.lag_hours:.1f}ч после производства"))
    lines += _named_rows(
        unmeasured, kind_label="НЕ ИЗМЕРЕНО", max_rows=max_rows,
        line=lambda v: f"  [НЕ ИЗМЕРЕНО] {v.artifact}: {v.reason}")
    return lines


def _office_moments(data_dir: Path) -> tuple[dict[str, str], dict[str, Optional[dt.datetime]]]:
    """Перечень и моменты — у ОФИСА, чтобы не завести второй дом величины."""
    import importlib.util
    import json

    office = _REPO_ROOT / "scripts" / "consume_office_reports.py"
    spec = importlib.util.spec_from_file_location("_spa_office_probe", office)
    if spec is None or spec.loader is None:
        raise Unmeasured(f"офис не загружается как модуль: {office}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    moments: dict[str, Optional[dt.datetime]] = {}
    for name in mod._PRODUCER:
        path = data_dir / name
        if not path.is_file():
            moments[name] = None
            continue
        try:
            moments[name] = mod._produced_moment(name, json.loads(path.read_text()))
        except (OSError, ValueError):
            moments[name] = None
    return dict(mod._PRODUCER), moments


def main(argv: Optional[Sequence[str]] = None) -> int:
    """0 — все выводы сегодняшней редакции · 1 — есть прежние · 2 — НЕ ИЗМЕРЕНО."""
    ap = argparse.ArgumentParser(
        description="Чья редакция произвела вывод артефакта офиса")
    ap.add_argument("--data-dir", default=str(_REPO_ROOT / "data"),
                    help="каталог артефактов (обычно <прод>/data)")
    ap.add_argument("--repo", action="append", dest="repos",
                    help="клон-кандидат; порядок объявлен, выбор печатается")
    ap.add_argument("--ref", default=REF_DEFAULT)
    ap.add_argument("--all", action="store_true",
                    help="печатать ВСЕ имена без предела строк: цикл, идущий "
                         "ПОИМЁННО, иначе получит часть под полным числом")
    ap.add_argument("--max-rows", type=int, default=12,
                    help="предел строк у КАЖДОГО рода (умолчание 12); "
                         "умолчанный остаток ВСЕГДА объявляется числом")
    args = ap.parse_args(argv)

    try:
        producers, moments = _office_moments(Path(args.data_dir))
    except Unmeasured as exc:
        print(f"РЕДАКЦИЯ ПРОИЗВОДИТЕЛЕЙ НЕ ИЗМЕРЕНА: {exc}")
        return 2
    c = measure(producers, moments, repos=args.repos, ref=args.ref)
    for line in report(c, max_rows=None if args.all else args.max_rows):
        print(line)
    if not c.measured:
        return 2
    if c.by_kind(STALE_EDITION):
        return 1
    return 2 if c.by_kind(UNMEASURED) and not c.by_kind(CURRENT) else 0


if __name__ == "__main__":
    raise SystemExit(main())
