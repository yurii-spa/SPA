#!/usr/bin/env python3
"""Перемер члена класса «вывод прежней редакции»: ЖИВЁТ ли напечатанная находка.

:mod:`spa_core.monitoring.artifact_edition` (ADR-1020/1021) отвечает на вопрос
«тот ли КОД вынес эту находку, который лежит в дереве сегодня», и ответ у него
**датный**: производитель правлен ПОЗЖЕ производства ⇒ артефакт несёт вывод
прежней редакции. Этого достаточно, чтобы ОСТАНОВИТЬ действие по красной строке,
и НЕДОСТАТОЧНО, чтобы сказать, что находки больше нет: «редакция сменилась» не
значит «вывод изменился».

Разделяет их ровно один замер — **прогон СЕГОДНЯШНЕГО производителя на
СЕГОДНЯШНИХ данных**, и до этого модуля он делался руками. Цена ручного пути
измерена заказом G1010: #1159 перемерил ЧЕТЫРЕ члена из восемнадцати, назвал
один неперемеряемым, и исходы четырёх оказались РАЗНЫМИ (36 → 1 · FINDINGS →
CLEAN · подтвердилась · находки не было вовсе). То есть род перемера не
угадывается по дате ни в одну сторону, а тринадцать членов остались без ответа —
и «они верны» из этого не следует.

## Что здесь объявлено, и почему объявление — ТАБЛИЦА, а не форма `--help`

У перемера есть одна предпосылка: производителя надо запустить так, чтобы он
**НЕ ТРОНУЛ прод-артефакт**. Заказ G1010 п. 1 назвал шесть членов, у которых
«входа песочницы НЕТ вовсе (ни ``--data-dir``, ни ``--out``)», и это измерение
было **НЕВЕРНЫМ** — оно спрашивало про ИМЯ входа, а не про его работу. Замер
этого модуля (цикл #1160): у пяти из шести вход есть и зовётся ``--root``, и он
перенаправляет НЕ ТОЛЬКО предмет чтения, но и запись —
``atomic_save(doc, os.path.join(root, REPORT_REL))``; у шестого
(``cio_component_map``) вход берётся из окружения (``SPA_ROOT``), поэтому в
``--help`` его не видно ВООБЩЕ. Входа не имеет **ни один** член класса.

Отсюда форма объявления: :data:`ENTRY` — закрытая таблица «артефакт → как его
произвести в песочнице», и проверяется она **ПРОГОНОМ** (появился артефакт в
песочнице ⇒ вход работает), а не чтением справки. Члена в таблице нет ⇒ исход
:data:`UNMEASURED` с названной причиной, а НЕ «подтвердилась»: fail-CLOSED.

## Три исхода, и почему их именно три (инв. #17)

* :data:`CONFIRMED` — набор находок сегодняшнего прогона СОВПАЛ с напечатанным:
  починки не было либо она находку не тронула. По такой строке действовать можно.
* :data:`CHANGED` — набор РАЗОШЁЛСЯ, и разность названа числами (ушло/пришло).
  Это и есть «напечатанное больше не правда»; по строке действовать нельзя.
* :data:`UNMEASURED` — перемера НЕ БЫЛО, с причиной. Сюда попадают: члена нет в
  таблице · прогон не завершился в бюджете · артефакт песочницы не появился ·
  форму находок сравнить нечем · перемер НЕ ЯВЛЯЕТСЯ ЧИТАЮЩИМ (см. :data:`ENTRY`
  о ``findings_bridge``: его производство требует ``--run``, который заводит
  карточки и шлёт уведомление владельцу — внешнее действие, а не замер).

Слить третий исход со первым значило бы объявить неизмеренное подтверждённым —
ровно тот дефект, из-за которого CRITICAL об инварианте #3 печатался двенадцать
циклов (ADR-1020 § «Авария»).

## Почему бюджет спрашивается у ПРОЦЕССА, а не у `timeout`

Заказ G1010 п. 1 несёт замер: ``ledger_day_unit_census`` жил **8 мин 41 с** под
``timeout 240``, и снял его не ``timeout``, а ``pkill``. «Прошло больше предела
⇒ прибор снят» — предположение, не вывод. Поэтому бюджет здесь — вход
(:data:`BUDGET_S`), снятие делает сам модуль (``kill`` → ``wait``), и **смерть
ПРОВЕРЯЕТСЯ** у того же pid; процесс пережил снятие ⇒ это :data:`UNMEASURED` с
этой причиной, а не «не уложился».

## Чего модуль НЕ делает

Не пишет в прод: корень песочницы, разрешившийся в прод-дерево, — ОТКАЗ до
первого прогона (:func:`refuse_prod_root`), и дом величины «где прод» здесь не
второй — он один, :data:`spa_core.utils.live_paths.DEFAULT_LIVE_ROOT`. Не судит
ПРИЧИНУ расхождения: сдвинуться могли и редакция, и данные, и разделяет их
отдельный замер (G1010 п. 2) — этот модуль отвечает «живёт ли находка», а не
«почему она умерла». Не чинит ни одного производителя.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from spa_core.monitoring import artifact_edition as ae
from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT

_REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIRMED = "confirmed"
CHANGED = "changed"
UNMEASURED = "unmeasured"

#: Бюджет ОДНОГО перемера, секунды. Вход, а не константа у вызова: у членов
#: класса разброс от 1 с (`cio_auto_execution_limits`) до минут (`orphan_sweep`),
#: и единственное, что про него известно наперёд, — что он у них разный.
BUDGET_S = 900.0

#: Поля, в которых производители офиса держат ТЕКСТ находки. Перечень ЗАКРЫТ:
#: находка, у которой ни одного из них нет, сравнению не поддаётся и честно
#: уходит в третий исход. Подставить сюда `str(dict)` было бы хуже пустоты —
#: порядок ключей и дрейф служебных полей дали бы «разошлось» на равных наборах.
TEXT_FIELDS = ("message", "text", "card", "line", "title", "key", "code")


@dataclass(frozen=True)
class Entry:
    """Как произвести ОДИН артефакт в песочнице.

    ``argv`` — шаблон: ``{root}`` подставляется корнем песочницы, ``{data}`` —
    её каталогом данных. ``refusal`` непуст ⇒ перемер этого члена ЧИТАЮЩИМ не
    является, и причина печатается вместо прогона.
    """

    argv: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    refusal: Optional[str] = None


#: Закрытая таблица песочных входов. Проверяется ПРОГОНОМ (отметка артефакта песочницы), а не
#: чтением `--help`: пять из шести «безвходных» членов заказа G1010 управляются
#: `--root`, шестой — переменной окружения, которой в справке нет вовсе.
ENTRY: dict[str, Entry] = {
    "cio_auto_execution_limits.json": Entry(
        ("-m", "spa_core.monitoring.cio_auto_execution_limits", "--root", "{root}")),
    "cio_architecture_constraints.json": Entry(
        ("-m", "spa_core.monitoring.cio_architecture_constraints", "--root", "{root}")),
    "cio_failure_modes.json": Entry(
        ("-m", "spa_core.monitoring.cio_failure_modes", "--root", "{root}")),
    "cio_target_producers.json": Entry(
        ("-m", "spa_core.monitoring.cio_target_producers", "--root", "{root}")),
    # Вход есть, но его НЕТ в `--help`: `main()` читает `SPA_ROOT` из окружения.
    # Ровно этот член заказ G1010 назвал «входа не имеет вовсе».
    "cio_component_map.json": Entry(
        ("-m", "spa_core.monitoring.cio_component_map",), {"SPA_ROOT": "{root}"}),
    "decision_journal_coverage.json": Entry(
        ("-m", "spa_core.monitoring.decision_journal_coverage", "--data-dir", "{data}")),
    "decision_reproducibility.json": Entry(
        ("-m", "spa_core.monitoring.decision_reproducibility",
         "--data-dir", "{data}", "--root", "{root}")),
    "asset_registry_gap_price.json": Entry(
        ("-m", "spa_core.monitoring.asset_registry_gap_price",
         "--data-dir", "{data}", "--root", "{root}")),
    "s49_surface_freshness.json": Entry(
        ("-m", "spa_core.monitoring.s49_surface_freshness",
         "--data-dir", "{data}", "--root", "{root}")),
    "pre_trade_recheck_census.json": Entry(
        ("-m", "spa_core.monitoring.pre_trade_recheck_census",
         "--data-dir", "{data}", "--repo-root", "{root}")),
    "orphan_sweep.json": Entry(
        ("-m", "spa_core.monitoring.orphan_sweep",
         "--repo-root", "{root}", "--out", "{data}/orphan_sweep.json")),
    "ledger_window_dependency.json": Entry(
        ("-m", "spa_core.monitoring.ledger_window_dependency_census",
         "--data-dir", "{data}")),
    "ledger_parse_census.json": Entry(
        ("-m", "spa_core.monitoring.ledger_parse_census", "--data-dir", "{data}")),
    "answer_list_order.json": Entry(
        ("-m", "spa_core.monitoring.answer_list_order_census", "--data-dir", "{data}")),
    "slo_keepability.json": Entry(
        ("-m", "spa_core.monitoring.slo_keepability", "--data-dir", "{data}")),
    # Перемер НЕ ЧИТАЮЩИЙ: производство требует `--run`, а он заводит карточки
    # (`orchestrator_queue create`) и шлёт уведомление владельцу. Внешнее
    # действие замером быть не может — и это ИСХОД, а не пропуск строки.
    "findings_bridge_report.json": Entry(refusal=(
        "производство требует `--run`, который заводит карточки и уведомляет "
        "владельца: внешнее действие, а не замер (плюс ступень переписей на "
        "живом Маке идёт часами)")),
    # То же по другой причине: вердикт собирается из прогона GitHub Actions,
    # то есть из состояния ЧУЖОЙ службы, а не из дерева и данных. Перемер
    # ответил бы о сегодняшнем прогоне CI, а не о редакции производителя.
    "ci_control_verdict.json": Entry(refusal=(
        "вердикт собирается из прогона GitHub Actions — предмет живёт у чужой "
        "службы, и прогон сегодня ответил бы о ДРУГОМ прогоне, а не о редакции")),
    # Член, названный #1159 неперемеряемым ПО БЮДЖЕТУ: 8 мин 41 с под
    # `timeout 240`, снят `pkill`. Причина оставлена здесь, чтобы прибор
    # называл её сам, а не наследовал из заказа.
    "ledger_day_unit_census.json": Entry(
        ("-m", "spa_core.monitoring.ledger_day_unit_census", "--data-dir", "{data}")),
}


@dataclass(frozen=True)
class Outcome:
    """Исход перемера ОДНОГО члена. `reason` обязателен у :data:`UNMEASURED`."""

    kind: str
    artifact: str
    before: Optional[int] = None
    after: Optional[int] = None
    gone: tuple[str, ...] = ()
    arrived: tuple[str, ...] = ()
    elapsed_s: Optional[float] = None
    reason: Optional[str] = None


@dataclass
class Census:
    """Замер по всем переданным членам класса."""

    outcomes: list[Outcome] = field(default_factory=list)
    sandbox_root: Optional[str] = None
    reason: Optional[str] = None
    generated_at: Optional[str] = None

    @property
    def measured(self) -> bool:
        return self.reason is None

    def by_kind(self, kind: str) -> list[Outcome]:
        return [o for o in self.outcomes if o.kind == kind]


class Refused(Exception):
    """Предпосылка перемера НЕ ОБЕСПЕЧЕНА — громко, а не вердиктом."""


def refuse_prod_root(root: Path) -> None:
    """Корень песочницы, совпавший с прод-деревом или лежащий в нём, — ОТКАЗ.

    Проверка БЕЗУСЛОВНА, в отличие от :func:`live_paths.assert_not_prod_realpath`,
    которая молчит без маркера ``SPA_SANDBOX``: там умолчание обязано оставаться
    боевым, здесь боевого пути нет вовсе — перемер, пишущий в прод-артефакт,
    уничтожает предмет замера (напечатанную находку) ДО того, как её сравнят.

    Сравниваются REALPATH: символическая ссылка на прод внутри стенда уводит
    запись туда же, а сравнение строк этого не видит.
    """
    prod = DEFAULT_LIVE_ROOT.resolve() if DEFAULT_LIVE_ROOT.is_dir() else DEFAULT_LIVE_ROOT
    real = Path(root).resolve()
    if real == prod or prod in real.parents:
        raise Refused(
            f"корень песочницы {real} лежит в прод-дереве {prod}: перемер обязан "
            f"быть ЧИТАЮЩИМ, а производитель пишет по {{root}}/data/<имя>.json")


def finding_keys(doc: Any) -> tuple[Optional[tuple[str, ...]], Optional[str]]:
    """Сравнимый набор находок артефакта — или названная причина, почему его нет.

    Ключ находки — ``severity`` плюс первое присутствующее из :data:`TEXT_FIELDS`.
    Текст берётся целиком: обрезать его значило бы склеить две находки, чьи
    первые сто символов совпали, и выдать «ушла одна» за «набор тот же».
    """
    if not isinstance(doc, dict):
        return None, f"артефакт не словарь, а {type(doc).__name__}"
    items = doc.get("findings")
    if items is None:
        return None, "у артефакта нет поля `findings` — сравнивать нечего"
    if not isinstance(items, list):
        return None, f"`findings` не список, а {type(items).__name__}"
    keys: list[str] = []
    for i, f in enumerate(items):
        if not isinstance(f, dict):
            keys.append(f"{i}:{f!r}")
            continue
        text = next((str(f[k]) for k in TEXT_FIELDS if f.get(k) is not None), None)
        if text is None:
            return None, (f"находка #{i} не несёт ни одного из объявленных полей "
                          f"текста {TEXT_FIELDS}: сравнить её нечем")
        keys.append(f"{f.get('severity') or '-'}|{text}")
    return tuple(sorted(keys)), None


def _produce(entry: Entry, *, root: Path, data: Path,
             budget_s: float) -> tuple[Optional[float], Optional[str], str]:
    """Запустить производителя в песочнице.

    Возвращает ``(секунды, причина отказа, хвост stderr)``. Код возврата здесь
    вердиктом НЕ является: у производителей офиса ``1`` означает «находки есть»,
    и судить по нему значило бы объявить находку отказом. Единственный отказ,
    который виден здесь, — несостоявшийся прогон (бюджет); состоялась ли ЗАПИСЬ,
    судит вызывающий по отметке артефакта, а ``stderr`` ему нужен, чтобы НАЗВАТЬ
    причину, если записи не случилось.

    Снятие по бюджету ПРОВЕРЯЕТСЯ у того же pid: `timeout` в замере #1159 предел
    не исполнил, и «прошло больше бюджета» выводом о снятии не является.
    """
    argv = [sys.executable, *[a.format(root=root, data=data) for a in entry.argv]]
    env = dict(os.environ)
    env.update({k: v.format(root=root, data=data) for k, v in entry.env.items()})
    # Предмет прогона — дерево песочницы: и `cwd`, и путь импорта должны вести
    # туда, иначе производитель прочитал бы СВОЙ код из дерева вызова.
    env["PYTHONPATH"] = os.pathsep.join([str(root), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    # Маркер песочницы C8(b) (ADR-580, храповик `test_sandbox_wiring_ratchet`; закрыто
    # ADR-1038): производитель импортирует ДЕРЕВО, на которое переставлен `PYTHONPATH`, и
    # читатель без своего параметра `data_dir` молча ушёл бы в ПРОД — класс INC-1. Маркер
    # идёт СО СВОЕЙ песочницей: `refuse_prod_root` выше уже отказал на корне внутри прода,
    # поэтому `root`/`data` здесь заведомо не прод. Значение, НАЗВАННОЕ записью реестра
    # (`entry.env`), сильнее этого умолчания; унаследованное от родителя — слабее, иначе
    # чужой `SPA_DATA_DIR` увёл бы запись из песочницы.
    for _key, _value in (("SPA_LIVE_ROOT", str(root)), ("SPA_DATA_DIR", str(data))):
        if _key not in entry.env:
            env[_key] = _value
    env["SPA_SANDBOX"] = "1"
    started = time.monotonic()
    proc = subprocess.Popen(argv, cwd=str(root), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        _, err = proc.communicate(timeout=budget_s)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            return None, (f"прогон не уложился в бюджет {budget_s:.0f} с И ПЕРЕЖИЛ "
                          f"снятие (pid {proc.pid} жив после SIGKILL+30 с) — "
                          f"исход НЕ ИЗМЕРЕН, а не «не уложился»"), ""
        return None, f"прогон не уложился в бюджет {budget_s:.0f} с, снят SIGKILL", ""
    elapsed = round(time.monotonic() - started, 1)
    return elapsed, None, (err or "")[-400:]


def remeasure_one(artifact: str, *, prod_data: Path, sandbox_root: Path,
                  budget_s: float = BUDGET_S,
                  entries: Optional[Mapping[str, "Entry"]] = None) -> Outcome:
    """Перемерить ОДИН член класса. Исход — один из трёх, всегда с причиной у третьего.

    ``entries`` — таблица песочных входов ВХОДОМ (умолчание :data:`ENTRY`, боевой
    путь не меняется ни одним вызовом). Нужна она не для удобства сцен: сосед
    :mod:`spa_core.monitoring.edition_cause` судит ту же таблицу своим гейтом и
    зовёт эту функцию проводкой, а «параметр есть у гейта, у проводки нет» —
    ровно та половина инъекции, которую `.claude/rules/deployment.md` § «ЛИЧНОСТЬ
    ПРОЦЕССА» называет той же бомбой (замер #453).
    """
    # Умолчание разрешается В МОМЕНТ ЗОВА, а не в момент определения: значение
    # по умолчанию `= ENTRY` связало бы ИМЕННО ТОТ словарь, что существовал при
    # импорте, и подмена объявленного дома таблицы перестала бы доходить до
    # проводки — своя же батарея ушла в красное на десяти пробах (замер #1161).
    table = ENTRY if entries is None else entries
    entry = table.get(artifact)
    if entry is None:
        return Outcome(UNMEASURED, artifact, reason=(
            "песочного входа у этого члена НЕ ОБЪЯВЛЕНО: запускать производителя "
            "наугад значило бы рискнуть записью в прод-артефакт"))
    if entry.refusal:
        return Outcome(UNMEASURED, artifact, reason=entry.refusal)

    before_doc = _read(prod_data / artifact)
    if before_doc is None:
        return Outcome(UNMEASURED, artifact, reason=(
            f"напечатанный артефакт не прочитан: {prod_data / artifact}"))
    before, why = finding_keys(before_doc)
    if before is None:
        return Outcome(UNMEASURED, artifact, reason=f"напечатанный набор: {why}")

    data = sandbox_root / "data"
    stamp_before = _mtime(data / artifact)
    elapsed, refusal, err = _produce(entry, root=sandbox_root, data=data,
                                     budget_s=budget_s)
    if refusal is not None:
        return Outcome(UNMEASURED, artifact, elapsed_s=elapsed, reason=refusal)
    if _mtime(data / artifact) == stamp_before:
        return Outcome(UNMEASURED, artifact, elapsed_s=elapsed, reason=(
            "артефакт песочницы НЕ ОБНОВИЛСЯ: объявленный вход записи не "
            "перенаправил, и сравнивать было бы НЕЧЕГО (а прод мог быть тронут)"
            + (f"; stderr: {err}" if err else "")))
    after_doc = _read(data / artifact)
    after, why = finding_keys(after_doc)
    if after is None:
        return Outcome(UNMEASURED, artifact, elapsed_s=elapsed,
                       reason=f"перемеренный набор: {why}")

    gone = tuple(sorted(set(before) - set(after)))
    arrived = tuple(sorted(set(after) - set(before)))
    kind = CONFIRMED if not gone and not arrived else CHANGED
    return Outcome(kind, artifact, before=len(before), after=len(after),
                   gone=gone, arrived=arrived, elapsed_s=elapsed)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _mtime(path: Path) -> Optional[int]:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def stale_members(data_dir: Path, *, repos: Optional[Sequence[str]] = None,
                  ref: str = ae.REF_DEFAULT) -> tuple[list[str], Optional[str]]:
    """Члены класса — у ЕДИНСТВЕННОГО прибора редакции, своей копии даты здесь нет."""
    try:
        producers, moments = ae._office_moments(data_dir)
    except Exception as exc:  # Unmeasured и всё, чем офис может не загрузиться
        return [], f"перечень артефактов не получен: {exc}"
    c = ae.measure(producers, moments, repos=repos, ref=ref)
    if not c.measured:
        return [], f"редакция производителей НЕ ИЗМЕРЕНА: {c.reason}"
    return [v.artifact for v in c.by_kind(ae.STALE_EDITION)], None


def run(*, prod_data: Path, sandbox_root: Path, only: Sequence[str] = (),
        budget_s: float = BUDGET_S, repos: Optional[Sequence[str]] = None,
        ref: str = ae.REF_DEFAULT, now: Optional[dt.datetime] = None,
        progress: bool = False) -> Census:
    """Перемерить перечень (по умолчанию — весь класс). ``now`` — ВХОД.

    ``progress`` — печать хода в ``stderr`` БЕЗ буфера. Прибор поднимает по
    подпроцессу на члена, и у восемнадцати членов такт идёт десятками минут;
    молчащий лог делает «работает» и «умер» НЕРАЗЛИЧИМЫМИ, а именно эта
    неразличимость пригласила неверное действие в аварии #906
    (`.claude/rules/deployment.md` § «ОКНО МУТАЦИОННОГО ПРИБОРА», п. 8).
    Умолчание ``False``: библиотечный вызов не вправе писать в чужой поток.
    """
    refuse_prod_root(sandbox_root)
    out = Census(sandbox_root=str(sandbox_root))
    names = list(only)
    if not names:
        names, why = stale_members(prod_data, repos=repos, ref=ref)
        if why is not None:
            out.reason = why
            return out
    for i, name in enumerate(names, 1):
        if progress:
            print(f"[перемер] {i}/{len(names)} {name} …", file=sys.stderr, flush=True)
        o = remeasure_one(name, prod_data=prod_data, sandbox_root=sandbox_root,
                          budget_s=budget_s)
        if progress:
            print(f"[перемер] {i}/{len(names)} {name} → {o.kind}"
                  f"{'' if o.elapsed_s is None else f' ({o.elapsed_s} с)'}",
                  file=sys.stderr, flush=True)
        out.outcomes.append(o)
    out.generated_at = (now or dt.datetime.now(dt.timezone.utc)).isoformat()
    return out


def report(c: Census, *, max_rows: Optional[int] = 12) -> list[str]:
    """Печать. Умолчанный остаток КАЖДОГО рода объявляется числом (ADR-1021)."""
    if not c.measured:
        return [f"ПЕРЕМЕР НЕ ИЗМЕРЕН: {c.reason}"]
    out = [f"перемер класса «вывод прежней редакции» (песочница {c.sandbox_root}):",
           f"  членов перемерено: {len(c.outcomes)}",
           f"  находка ПОДТВЕРДИЛАСЬ: {len(c.by_kind(CONFIRMED))}",
           f"  набор РАЗОШЁЛСЯ: {len(c.by_kind(CHANGED))}",
           f"  НЕ ИЗМЕРЕНО: {len(c.by_kind(UNMEASURED))}"]
    for kind, label in ((CHANGED, "РАЗОШЁЛСЯ"), (CONFIRMED, "ПОДТВЕРДИЛАСЬ"),
                        (UNMEASURED, "НЕ ИЗМЕРЕНО")):
        rows = c.by_kind(kind)
        shown = rows if max_rows is None else rows[:max_rows]
        for o in shown:
            if kind == UNMEASURED:
                out.append(f"  [{label}] {o.artifact}: {o.reason}")
            else:
                out.append(f"  [{label}] {o.artifact}: находок {o.before} → {o.after}"
                           f" (ушло {len(o.gone)}, пришло {len(o.arrived)})"
                           f" · {o.elapsed_s} с")
        if max_rows is not None and len(rows) > len(shown):
            out.append(f"  … ещё {len(rows) - len(shown)} в роде «{label}» "
                       f"(полный перечень — `--all`)")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    """0 — все подтвердились · 1 — есть разошедшиеся · 2 — НЕ ИЗМЕРЕНО."""
    ap = argparse.ArgumentParser(
        description="Живёт ли напечатанная находка на сегодняшнем производителе")
    ap.add_argument("--data-dir", default=str(_REPO_ROOT / "data"),
                    help="каталог НАПЕЧАТАННЫХ артефактов (обычно <прод>/data)")
    ap.add_argument("--sandbox-root", required=True,
                    help="корень одноразового дерева: сегодняшний код + копия живого "
                         "`data/`. Путь в прод-дереве — ОТКАЗ")
    ap.add_argument("--only", action="append", default=[],
                    help="перемерить названный артефакт (можно повторять)")
    ap.add_argument("--budget", type=float, default=BUDGET_S,
                    help=f"бюджет ОДНОГО прогона, с (умолчание {BUDGET_S:.0f}); "
                         f"снятие ПРОВЕРЯЕТСЯ у pid")
    ap.add_argument("--repo", action="append", dest="repos")
    ap.add_argument("--ref", default=ae.REF_DEFAULT)
    ap.add_argument("--now", help="момент замера, ISO-8601 (вход, не стенные часы)")
    ap.add_argument("--all", action="store_true",
                    help="печатать ВСЕ имена без предела строк")
    ap.add_argument("--max-rows", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="не печатать ход в stderr; молчащий лог делает "
                         "«работает» и «умер» неразличимыми — включать осознанно")
    args = ap.parse_args(argv)

    now = None
    if args.now:
        try:
            now = dt.datetime.fromisoformat(args.now)
        except ValueError:
            print(f"ОТКАЗ (код 2): --now не разобран: {args.now!r}", file=sys.stderr)
            return 2

    try:
        c = run(prod_data=Path(args.data_dir), sandbox_root=Path(args.sandbox_root),
                only=args.only, budget_s=args.budget, repos=args.repos,
                ref=args.ref, now=now, progress=not args.quiet)
    except Refused as exc:
        print(f"ОТКАЗ (код 2): {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"sandbox_root": c.sandbox_root, "reason": c.reason,
                          "outcomes": [o.__dict__ for o in c.outcomes]},
                         ensure_ascii=False, indent=2, default=str))
    else:
        for line in report(c, max_rows=None if args.all else args.max_rows):
            print(line)
    if not c.measured:
        return 2
    if c.by_kind(CHANGED):
        return 1
    return 2 if c.by_kind(UNMEASURED) and not c.by_kind(CONFIRMED) else 0


if __name__ == "__main__":
    raise SystemExit(main())
