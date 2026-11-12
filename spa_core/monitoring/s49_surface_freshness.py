#!/usr/bin/env python3
# LLM_FORBIDDEN
"""§49 приказа «Portfolio CIO» ВТОРОЙ осью — свежа ли ПОВЕРХНОСТЬ, с которой читают приёмку.

Заказ **G982 п. 1** (хвост ADR-993) дословно:

    «решить ПО INDEX: перемерять ли §49 ВТОРОЙ осью (что из мер читает
     `card_acceptance` сегодня и свеж ли каждый вход — ADR-770/790/811 нашли
     три молчавших производителя) или идти к §50–§52».

Решение — ВТОРОЙ осью, и причина измерена, а не выбрана. Тринадцать критериев
§49 получили меры (ADR-507…512, 808, 809, 810), сводка стала машинной (ADR-505),
такт сводки измерен (ADR-547), и каждая из этих работ отвечала на вопрос
«ВЫПОЛНЕН ли критерий». Ни одна не задавала соседнего: **а то, что лежит на
поверхности решения сегодня, — это вердикт о сегодняшнем мире или о прошлом?**

## Что нашёл замер 12.11 (цикл #1113, прод-`data/`)

* У **всех тринадцати** входов сводки возраст больше объявленного `slo_hours`:
  семь — 342 ч, четыре — 231 ч, `No regression` — 485 ч при пределе 192, и даже
  `Auditability` — 10,3 ч при пределе 9,28. Сама сводка `s49_tally_tact.json` —
  342 ч при пределе 14.
* Производитель у всех шестнадцати артефактов поверхности (13 входов + сводка +
  дерево приёмки + отчёт моста) **ОДИН** — `com.spa.decision_loop`, и во флоте
  его **нет** (служба OFF с 29.10, карточка
  `inbox-most-nahodok-decision-loop-ne-ukladyvaet`). Поверхность §49 замёрзла
  целиком одним выключателем: это не «три молчавших производителя» ADR-770/790/811,
  это один молчащий бегун и тринадцать его продуктов.
* Шаг 0-офис печатает замороженную сводку «ВЫПОЛНЕНО 0 · НЕ ВЫПОЛНЕНО 11 ·
  НЕ ИЗМЕРЕНО 2» с пометкой «старше суток» — общий порог 24 ч, а не её
  собственный SLO 14 ч; протухание всех входов измерено соседом
  (`architecture_conformance`, класс B2), но из 123 WARN печатаются 7, и §49-е
  лежат под строкой «… ещё 116 находок».
* Живая сводка (пробы ГОНЯЮТСЯ, а не читают артефакт) даёт сегодня
  **ВЫПОЛНЕНО 1 · НЕ ВЫПОЛНЕНО 9 · НЕ ИЗМЕРЕНО 3**: `Owner visibility`
  не измерено → выполнено, `Determinism` и `Shadow verification` не выполнено →
  не измерено («артефакт протух … сегодняшнего ответа прибора нет, а вчерашний за
  него не выдаётся»). Замороженная поверхность завышает «не выполнено» на два и
  скрывает единственное «выполнено».

## Три вопроса прибора, и каждый с третьим исходом (инв. #17)

1. **Свеж ли каждый вход?** Привязка «критерий → артефакт → `slo_hours`» берётся
   у соседа (`s49_tally_tact.tact_floor` → `s49_criterion_price.parse_bindings`),
   второй копии правила здесь нет (ADR-220). Исходы у входа: `fresh` · `stale`
   · `absent` · `no_clock` (файл есть, часов в нём нет — возраст НЕ ИЗМЕРЕН) ·
   `unbound` (привязки или срока нет — сравнивать нечем).
2. **Кто производит и жив ли он?** Производитель — из конституции; живость —
   у флота (`launchctl list`), и это ВХОД: `loaded=None` означает «флот не
   спрошен», и тогда производитель получает `fleet_unmeasured`, а не «мёртв» и
   не «жив». Молчание производителя измеряется САМЫМ СВЕЖИМ его артефактом.
3. **Совпадает ли замороженная сводка с живой?** Живые строки — ВХОД
   (`live_rows`, обычно из `cio_acceptance_rollup --json`); прибор их не снимает
   сам, потому что сводка стои́т 76 с и своего такта (ADR-547). Без входа ось
   честно `UNCHECKED`, а не «дрейфа нет».

## Чего прибор НЕ докладывает

* Верна ли живая проба — это держит её контроль в обе стороны
  (`.claude/rules/acceptance.md`, п. 3), не этот прибор.
* Почему бегун выключен — у этого вопроса своя карточка; здесь измеряется
  только, ЧТО от его молчания видит поверхность.
* Ничего не чинит и не включает: ADVISORY, читает конституцию, артефакты и
  список флота; `landing/**`, RiskPolicy, стоп-кран, аллокатор не трогаются.

## Коды возврата

* **0** — замер состоялся, поверхность свежа (находок critical нет).
* **1** — замер состоялся и есть находка (входы протухли · производитель не
  загружен · сводка расходится с живой).
* **2** — замера НЕТ ВОВСЕ (конституция или население §49 не прочитаны).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring import s49_criterion_price as price_meter  # noqa: E402
from spa_core.monitoring import s49_tally_tact as tally_meter  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

SCHEMA = "s49_surface_freshness/v1"
REPORT_REL = "data/s49_surface_freshness.json"
TALLY_REL = "data/s49_tally_tact.json"
ADR = "ADR-994"

#: Исходы у ОДНОГО входа сводки.
FRESH = "fresh"
STALE = "stale"
ABSENT = "absent"
NO_CLOCK = "no_clock"
UNBOUND = "unbound"
INPUT_STATES = (FRESH, STALE, ABSENT, NO_CLOCK, UNBOUND)

#: Исходы у производителя.
LOADED = "loaded"
NOT_LOADED = "not_loaded"
FLEET_UNMEASURED = "fleet_unmeasured"
PRODUCER_UNKNOWN = "producer_unknown"

#: Исходы оси «замороженная сводка против живой».
DRIFT_MEASURED = "measured"
DRIFT_UNCHECKED = "UNCHECKED"

OVERALL_OK = "OK"
OVERALL_WARN = "WARN"
OVERALL_CRITICAL = "CRITICAL"
OVERALL_UNCHECKED = "UNCHECKED"

ADVISORY = ("ADVISORY: прибор только ЧИТАЕТ конституцию, артефакты и список флота; "
            "ничего не включает, не пишет в чужие артефакты, не трогает RiskPolicy, "
            "стоп-кран, аллокатор, живой трек и landing/**")

NOT_REPORTED = ("НЕ ДОКЛАДЫВАЕТ: верна ли живая проба (её держит контроль в обе стороны) · "
                "почему бегун выключен (своя карточка) · зовущего вне состава ступеней")


class Unmeasured(Exception):
    """Замера нет вовсе. О свежести поверхности при этом не сказано НИЧЕГО."""


# ─────────────────────────── часы и чтение ───────────────────────────

def _now(now: Optional[dt.datetime]) -> dt.datetime:
    return now if now is not None else dt.datetime.now(dt.timezone.utc)


def parse_ts(value: Any) -> Optional[dt.datetime]:
    """ISO-8601 → aware datetime; всё остальное → None (часов НЕТ, а не «ноль»)."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def read_json(path: Path) -> tuple[Optional[Any], Optional[str]]:
    """(документ, None) либо (None, причина). Отсутствие и нечитаемость — разные причины."""
    if not path.is_file():
        return None, "файла нет"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"не прочитан: {type(exc).__name__}: {exc}"


def age_hours(doc: Any, now: dt.datetime) -> Optional[float]:
    """Возраст по `generated_at` документа. Нет отметки или не разобрана → None."""
    stamp = parse_ts(observed(doc, "generated_at", kind=str))
    if stamp is None:
        return None
    return round((now - stamp).total_seconds() / 3600.0, 2)


# ─────────────────────────── 1. свежесть входов ───────────────────────────

def artifact_path(data_dir: Path, artifact: str) -> Path:
    """`data/<rel>` конституции → файл в КАТАЛОГЕ артефактов (вложенность сохраняется)."""
    rel = artifact[len("data/"):] if artifact.startswith("data/") else artifact
    return data_dir / rel



def input_rows(tact_rows: Iterable[dict], *, data_dir: Path, now: dt.datetime) -> list[dict]:
    """У каждого критерия: его вход, срок, возраст и исход.

    `tact_rows` — строки `s49_tally_tact.tact_floor(...)["rows"]`: привязка и
    срок читаются ОДНОЙ дверью с соседом, своей копии правила здесь нет.
    """
    rows: list[dict] = []
    for tr in tact_rows:
        criterion = tr.get("criterion")
        artifact = tr.get("artifact")
        slo = tr.get("slo_hours")
        row: dict[str, Any] = {"criterion": criterion, "artifact": artifact,
                               "slo_hours": slo, "age_hours": None,
                               "generated_at": None, "state": None, "why": None}
        if tr.get("state") != tally_meter.TACT_BOUND or not isinstance(slo, (int, float)) \
                or isinstance(slo, bool) or not artifact:
            row["state"] = UNBOUND
            row["why"] = ("привязки с объявленным сроком нет — "
                          f"{tr.get('why') or 'причина соседом не названа'}")
            rows.append(row)
            continue
        path = artifact_path(data_dir, str(artifact))
        doc, problem = read_json(path)
        if doc is None:
            row["state"] = ABSENT
            row["why"] = f"{artifact}: {problem}"
            rows.append(row)
            continue
        row["generated_at"] = observed(doc, "generated_at", kind=str)
        age = age_hours(doc, now)
        if age is None:
            row["state"] = NO_CLOCK
            row["why"] = (f"{artifact}: файл есть, а `generated_at` нет или не разобран — "
                          "возраст НЕ ИЗМЕРЕН, свежим не считается")
            rows.append(row)
            continue
        row["age_hours"] = age
        if age > float(slo):
            row["state"] = STALE
            row["why"] = f"{artifact}: возраст {age:.1f} ч > SLO {float(slo):g} ч"
        else:
            row["state"] = FRESH
            row["why"] = f"{artifact}: возраст {age:.1f} ч ≤ SLO {float(slo):g} ч"
        rows.append(row)
    return rows


def input_counts(rows: Iterable[dict]) -> dict[str, int]:
    counts = {state: 0 for state in INPUT_STATES}
    for row in rows:
        state = row.get("state")
        if state in counts:
            counts[state] += 1
    return counts


# ─────────────────────────── 2. производители и флот ───────────────────────────

def producer_of(manifest: dict, artifact: Optional[str]) -> Optional[str]:
    """Производитель артефакта по конституции; не объявлен → None."""
    if not artifact:
        return None
    for entry in manifest.get("artifacts") or ():
        if isinstance(entry, dict) and entry.get("path") == artifact:
            producer = entry.get("producer")
            return str(producer) if isinstance(producer, str) and producer else None
    return None


def fleet_loaded(runner: Callable[..., Any] = subprocess.run) -> Optional[set[str]]:
    """Метки загруженных служб из `launchctl list`; спросить не вышло → None.

    `None` — третий исход: «флот не спрошен» ≠ «служб нет». Подставить пустое
    множество значило бы объявить ВСЕХ производителей незагруженными.
    """
    try:
        proc = runner(["launchctl", "list"], capture_output=True, text=True,
                      timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not isinstance(proc.stdout, str):
        return None
    labels: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].strip() and parts[2].strip() != "Label":
            labels.add(parts[2].strip())
    return labels


def producer_rows(inputs: Iterable[dict], *, manifest: dict,
                  loaded: Optional[set[str]], now: dt.datetime) -> list[dict]:
    """Производители входов: сколько критериев на каждом, жив ли, когда молчит.

    Молчание измеряется САМЫМ СВЕЖИМ артефактом производителя среди входов:
    «не загружен» говорит о сегодня, «молчит N ч» — с какого момента.
    """
    by_producer: dict[Optional[str], list[dict]] = {}
    for row in inputs:
        if row.get("state") == UNBOUND:
            continue
        producer = producer_of(manifest, row.get("artifact"))
        by_producer.setdefault(producer, []).append(row)

    rows: list[dict] = []
    for producer, group in sorted(by_producer.items(), key=lambda kv: str(kv[0])):
        stamped = [(parse_ts(r.get("generated_at")), r.get("artifact")) for r in group]
        stamped = [(s, a) for s, a in stamped if s is not None]
        newest = max(stamped, key=lambda sa: sa[0]) if stamped else None
        last_seen = newest[0].isoformat() if newest else None
        last_seen_artifact = newest[1] if newest else None
        silent_h = round((now - newest[0]).total_seconds() / 3600.0, 2) if newest else None
        if producer is None:
            state = PRODUCER_UNKNOWN
            why = "конституция не называет производителя — спросить флот не о ком"
        elif loaded is None:
            state = FLEET_UNMEASURED
            why = "флот не спрошен (`launchctl list` не ответил) — живость НЕ ИЗМЕРЕНА"
        elif producer in loaded:
            state = LOADED
            why = "служба загружена во флоте"
        else:
            state = NOT_LOADED
            why = "службы нет в `launchctl list` — производитель выключен"
        rows.append({"producer": producer, "criteria": [r.get("criterion") for r in group],
                     "criteria_count": len(group),
                     "stale_count": sum(1 for r in group if r.get("state") == STALE),
                     "state": state, "last_seen": last_seen,
                     "last_seen_artifact": last_seen_artifact,
                     # Нижняя граница молчания: самый свежий файл мог написать и
                     # ДРУГОЙ, необъявленный писатель (класс ADR-811) — артефакт
                     # назван, чтобы читатель мог спросить об этом сам.
                     "silent_hours": silent_h, "why": why})
    return rows


# ─────────────────────────── 3. сводка: замороженная против живой ───────────────────────────

def tally_state(data_dir: Path, *, manifest: dict, now: dt.datetime) -> dict:
    """Что лежит на поверхности: счёт сводки, её возраст и срок."""
    path = artifact_path(data_dir, TALLY_REL)
    doc, problem = read_json(path)
    slo = None
    for entry in manifest.get("artifacts") or ():
        if isinstance(entry, dict) and entry.get("path") == TALLY_REL:
            cand = entry.get("slo_hours")
            if isinstance(cand, (int, float)) and not isinstance(cand, bool):
                slo = float(cand)
    out: dict[str, Any] = {"artifact": TALLY_REL, "slo_hours": slo, "state": None,
                           "age_hours": None, "generated_at": None,
                           "counts": None, "rows": [], "why": None}
    if doc is None:
        out["state"] = ABSENT
        out["why"] = f"{TALLY_REL}: {problem}"
        return out
    counts = observed(doc, "tally", kind=dict)
    out["counts"] = dict(counts) if counts is not None else None
    tally_rows = observed(doc, "tally_rows", kind=list)
    out["rows"] = [{"criterion": r.get("criterion"), "verdict": r.get("verdict")}
                   for r in (tally_rows if tally_rows is not None else ()) if isinstance(r, dict)]
    out["generated_at"] = observed(doc, "generated_at", kind=str)
    age = age_hours(doc, now)
    if age is None:
        out["state"] = NO_CLOCK
        out["why"] = f"{TALLY_REL}: часов нет — возраст НЕ ИЗМЕРЕН"
        return out
    out["age_hours"] = age
    if slo is None:
        out["state"] = UNBOUND
        out["why"] = f"{TALLY_REL}: срок не объявлен в конституции — сравнивать нечем"
    elif age > slo:
        out["state"] = STALE
        out["why"] = f"{TALLY_REL}: возраст {age:.1f} ч > SLO {slo:g} ч"
    else:
        out["state"] = FRESH
        out["why"] = f"{TALLY_REL}: возраст {age:.1f} ч ≤ SLO {slo:g} ч"
    return out


def counts_of(rows: Iterable[dict]) -> dict[str, int]:
    counts = {v: 0 for v in tally_meter.VERDICT_VOCABULARY}
    for row in rows:
        verdict = row.get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    return counts


def drift(frozen_rows: Iterable[dict], live_rows: Optional[Iterable[dict]]) -> dict:
    """Расхождение замороженной сводки с живой — по критерию, с обеими сторонами.

    Живые строки — ВХОД. Их нет ⇒ `UNCHECKED` с причиной, а не «расхождения нет».
    Критерий, которого нет на одной из сторон, — отдельная строка (`missing`),
    а не молчаливый пропуск.
    """
    if live_rows is None:
        return {"verdict": DRIFT_UNCHECKED, "rows": [], "changed": 0,
                "frozen_counts": counts_of(frozen_rows), "live_counts": None,
                "reason": "живые строки сводки не переданы (`--rollup-json`/`--live`) — "
                          "ось не измерена"}
    frozen = {r.get("criterion"): r.get("verdict") for r in frozen_rows}
    live = {r.get("criterion"): r.get("verdict") for r in live_rows}
    rows: list[dict] = []
    for name in sorted(set(frozen) | set(live), key=str):
        f_v, l_v = frozen.get(name), live.get(name)
        if name not in frozen or name not in live:
            rows.append({"criterion": name, "frozen": f_v, "live": l_v, "kind": "missing"})
        elif f_v != l_v:
            rows.append({"criterion": name, "frozen": f_v, "live": l_v, "kind": "changed"})
    return {"verdict": DRIFT_MEASURED, "rows": rows,
            "changed": sum(1 for r in rows if r["kind"] == "changed"),
            "frozen_counts": counts_of(
                [{"verdict": v} for v in frozen.values()]),
            "live_counts": counts_of([{"verdict": v} for v in live.values()]),
            "reason": None}


# ─────────────────────────── находки ───────────────────────────

def findings(inputs: list[dict], producers: list[dict], tally: dict, drifted: dict) -> list[dict]:
    out: list[dict] = []
    ic = input_counts(inputs)
    bound = len(inputs) - ic[UNBOUND]
    stale_names = [r["criterion"] for r in inputs if r.get("state") == STALE]
    dead = [p for p in producers if p["state"] == NOT_LOADED]
    unmeasured_fleet = [p for p in producers if p["state"] == FLEET_UNMEASURED]

    if ic[STALE] and dead:
        worst = max(dead, key=lambda p: p["criteria_count"])
        silent = (f"самый свежий его продукт {worst['last_seen_artifact']} — "
                  f"{worst['silent_hours']:.0f} ч назад ({worst['last_seen']}; нижняя граница "
                  f"молчания: файл мог написать и необъявленный писатель)"
                  if worst.get("silent_hours") is not None
                  else "молчит, с какого момента — НЕ ИЗМЕРЕНО (часов в артефактах нет)")
        out.append({"severity": "critical", "key": "surface_frozen",
                    "text": (f"поверхность §49 ЗАМОРОЖЕНА: {ic[STALE]} из {bound} входов старше "
                             f"своего SLO ({', '.join(stale_names)}); производитель "
                             f"{worst['producer']} держит {worst['criteria_count']} из {bound} "
                             f"критериев и НЕ ЗАГРУЖЕН во флоте — {silent}")})
    elif ic[STALE]:
        out.append({"severity": "warn", "key": "inputs_stale",
                    "text": (f"{ic[STALE]} из {bound} входов §49 старше своего SLO "
                             f"({', '.join(stale_names)}), производитель во флоте есть — "
                             "бегун жив, а продукта нет: чинится не включением")})
    if unmeasured_fleet:
        out.append({"severity": "unchecked", "key": "fleet_unmeasured",
                    "text": ("живость производителя НЕ ИЗМЕРЕНА — флот не спрошен: "
                             + ", ".join(str(p["producer"]) for p in unmeasured_fleet))})
    if ic[ABSENT]:
        out.append({"severity": "warn", "key": "inputs_absent",
                    "text": (f"входов §49 нет на диске: {ic[ABSENT]} — "
                             + ", ".join(r["criterion"] for r in inputs if r.get("state") == ABSENT))})
    if ic[NO_CLOCK]:
        out.append({"severity": "unchecked", "key": "inputs_no_clock",
                    "text": (f"у {ic[NO_CLOCK]} входов нет часов — возраст НЕ ИЗМЕРЕН: "
                             + ", ".join(r["criterion"] for r in inputs if r.get("state") == NO_CLOCK))})
    if ic[UNBOUND]:
        out.append({"severity": "unchecked", "key": "inputs_unbound",
                    "text": (f"у {ic[UNBOUND]} критериев нет привязки со сроком — свежесть "
                             "сравнивать нечем: "
                             + ", ".join(r["criterion"] for r in inputs if r.get("state") == UNBOUND))})
    if len({p["producer"] for p in producers}) == 1 and producers and bound > 1:
        out.append({"severity": "info", "key": "single_producer",
                    "text": (f"все {bound} входов §49 производит ОДНА служба "
                             f"{producers[0]['producer']} — поверхность приёмки замерзает "
                             "одним выключателем")})

    if tally["state"] == STALE:
        c = tally.get("counts")
        shown = (f"ВЫПОЛНЕНО {c.get(tally_meter.SATISFIED)} · НЕ ВЫПОЛНЕНО "
                 f"{c.get(tally_meter.NOT_SATISFIED)} · НЕ ИЗМЕРЕНО {c.get(tally_meter.UNMEASURED)}"
                 if isinstance(c, dict) else "счёт не прочитан")
        out.append({"severity": "warn", "key": "tally_stale",
                    "text": (f"сводка на поверхности протухла: {tally['why']}; читатель видит "
                             f"«{shown}» как сегодняшний счёт")})
    elif tally["state"] in (ABSENT, NO_CLOCK, UNBOUND):
        out.append({"severity": "unchecked", "key": "tally_" + str(tally["state"]),
                    "text": f"сводка на поверхности: {tally['why']}"})

    if drifted["verdict"] == DRIFT_UNCHECKED:
        out.append({"severity": "unchecked", "key": "drift_unchecked",
                    "text": f"замороженная сводка против живой: {drifted['reason']}"})
    elif drifted["rows"]:
        named = "; ".join(f"{r['criterion']}: {r['frozen']} → {r['live']}" for r in drifted["rows"])
        fc, lc = drifted["frozen_counts"], drifted["live_counts"]
        out.append({"severity": "warn", "key": "tally_drift",
                    "text": (f"замороженная сводка расходится с живой у {len(drifted['rows'])} "
                             f"критериев ({named}); счёт на поверхности "
                             f"{fc[tally_meter.SATISFIED]}·{fc[tally_meter.NOT_SATISFIED]}·"
                             f"{fc[tally_meter.UNMEASURED]}, живой "
                             f"{lc[tally_meter.SATISFIED]}·{lc[tally_meter.NOT_SATISFIED]}·"
                             f"{lc[tally_meter.UNMEASURED]}")})
    else:
        out.append({"severity": "info", "key": "tally_same",
                    "text": "замороженная сводка совпадает с живой по каждому критерию"})
    return out


def _overall(found: list[dict]) -> str:
    sev = {f["severity"] for f in found}
    if "critical" in sev:
        return OVERALL_CRITICAL
    if "warn" in sev:
        return OVERALL_WARN
    if "unchecked" in sev:
        return OVERALL_UNCHECKED
    return OVERALL_OK


# ─────────────────────────── замер ───────────────────────────

def read_criteria(repo_root: str, *, ref: str = "origin/main") -> list[str]:
    """Население §49 — у канонической двери сводки (обе копии карточки)."""
    scripts = Path(repo_root) / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    try:
        import cio_acceptance_rollup as rollup  # noqa: PLC0415
    except ImportError as exc:
        raise Unmeasured(f"дверь населения §49 не ввезена: {exc}") from exc
    try:
        return list(rollup.read_population(repo_root, ref=ref)["criteria"])
    except rollup.Unmeasured as exc:
        raise Unmeasured(f"население §49 не прочитано: {exc}") from exc


def measure(repo_root: str | Path, *, data_dir: str | Path | None = None,
            now: Optional[dt.datetime] = None, criteria: Optional[list[str]] = None,
            tact_rows: Optional[list[dict]] = None, manifest: Optional[dict] = None,
            loaded: Optional[set[str]] = None, fleet_asked: bool = False,
            live_rows: Optional[list[dict]] = None, ref: str = "origin/main") -> dict:
    """Снять три оси. Часы, флот и живые строки — ВХОДЫ.

    `loaded=None` при `fleet_asked=False` означает «спросить флот самому»; при
    `fleet_asked=True` — «спросили, ответа нет» (третий исход). Контроль
    подменяет оба явно, чтобы ни одна сцена не упиралась в живой `launchctl`.
    """
    root = str(repo_root)
    data = Path(data_dir) if data_dir else Path(root) / "data"
    moment = _now(now)

    if manifest is None:
        try:
            manifest = price_meter.read_manifest(root)
        except price_meter.Unmeasured as exc:
            raise Unmeasured(f"конституция не прочитана: {exc}") from exc
    if criteria is None:
        criteria = read_criteria(root, ref=ref)
    if not criteria:
        raise Unmeasured("население §49 пусто — мерить нечего")
    if tact_rows is None:
        try:
            tact_rows = list(tally_meter.tact_floor(criteria, repo_root=root)["rows"])
        except tally_meter.Unmeasured as exc:
            raise Unmeasured(f"привязки §49 не прочитаны: {exc}") from exc
    rows_in: list[dict] = list(tact_rows)
    if loaded is None and not fleet_asked:
        loaded = fleet_loaded()

    inputs = input_rows(rows_in, data_dir=data, now=moment)
    producers = producer_rows(inputs, manifest=manifest, loaded=loaded, now=moment)
    tally = tally_state(data, manifest=manifest, now=moment)
    drifted = drift(tally["rows"], live_rows)
    found = findings(inputs, producers, tally, drifted)
    counts = {s: sum(1 for f in found if f["severity"] == s)
              for s in ("critical", "warn", "info", "unchecked")}
    return {
        "schema": SCHEMA,
        "adr": ADR,
        "generated_at": moment.isoformat(),
        "overall": _overall(found),
        "counts": counts,
        "repo_root": root,
        "data_dir": str(data),
        "population": len(criteria),
        "inputs": inputs,
        "input_counts": input_counts(inputs),
        "producers": producers,
        "fleet_measured": loaded is not None,
        "tally": tally,
        "drift": drifted,
        "findings": found,
        "not_reported": NOT_REPORTED,
        "advisory": ADVISORY,
    }


def live_rows_from_rollup(doc: Any) -> list[dict]:
    """Строки живой сводки из JSON `cio_acceptance_rollup --json`."""
    rows = observed(doc, "rows", kind=list)
    if rows is None:
        raise Unmeasured("в JSON сводки нет `rows` — живые вердикты не прочитаны")
    return [{"criterion": r.get("criterion"), "verdict": r.get("verdict")}
            for r in rows if isinstance(r, dict)]


def run(root: str | Path | None = None, *, data_dir: str | Path | None = None,
        write: bool = True, now: Optional[dt.datetime] = None,
        rollup_json: str | Path | None = None, live: bool = False, **kw) -> dict:
    """Собрать отчёт и (по умолчанию) записать `REPORT_REL` в корень дерева."""
    root_path = Path(root) if root else _REPO_ROOT
    live_rows = kw.pop("live_rows", None)
    if rollup_json is not None:
        doc, problem = read_json(Path(rollup_json))
        if doc is None:
            raise Unmeasured(f"JSON живой сводки {rollup_json}: {problem}")
        live_rows = live_rows_from_rollup(doc)
    elif live:
        scripts = root_path / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import cio_acceptance_rollup as rollup  # noqa: PLC0415
        data = str(data_dir) if data_dir else None
        try:
            live_rows = live_rows_from_rollup(rollup.measure(str(root_path), data_dir=data))
        except rollup.Unmeasured as exc:
            raise Unmeasured(f"живая сводка не снята: {exc}") from exc
    doc = measure(root_path, data_dir=data_dir, now=now, live_rows=live_rows, **kw)
    if write:
        from spa_core.utils.atomic import atomic_save  # noqa: PLC0415
        atomic_save(doc, str(root_path / REPORT_REL))
    return doc


# ─────────────────────────── отрисовка ───────────────────────────

def report(doc: dict, max_rows: int = 16) -> list[str]:
    lines: list[str] = []
    counts = observed(doc, "counts", kind=dict)
    ic = observed(doc, "input_counts", kind=dict)
    pop = observed(doc, "population", kind=int)
    lines.append(
        f"   Свежесть поверхности §49 (заказ G982 п. 1): {doc.get('overall') or 'НЕ ИЗМЕРЕНО'} "
        f"(critical={_n(counts, 'critical')} warn={_n(counts, 'warn')} "
        f"info={_n(counts, 'info')} unchecked={_n(counts, 'unchecked')}) · критериев "
        f"{pop if pop is not None else 'НЕ ИЗМЕРЕНО'}")
    lines.append(
        f"     входы: свежих {_n(ic, FRESH)} · протухших {_n(ic, STALE)} · нет на диске "
        f"{_n(ic, ABSENT)} · без часов {_n(ic, NO_CLOCK)} · без привязки {_n(ic, UNBOUND)}")
    for p in (observed(doc, "producers", kind=list) or [])[:max_rows]:
        silent = (f"молчит {p['silent_hours']:.0f} ч" if isinstance(p.get("silent_hours"), (int, float))
                  else "молчание НЕ ИЗМЕРЕНО")
        lines.append(f"     [{p.get('state')}] {p.get('producer')}: критериев "
                     f"{p.get('criteria_count')}, протухло {p.get('stale_count')}, {silent}")
    tally = observed(doc, "tally", kind=dict)
    if tally is not None:
        lines.append(f"     сводка: [{tally.get('state')}] {tally.get('why')}")
    drifted = observed(doc, "drift", kind=dict)
    if drifted is not None:
        if drifted.get("verdict") == DRIFT_MEASURED:
            lines.append(f"     живая против замороженной: расхождений {drifted.get('changed')}"
                         + ("".join(f" · {r['criterion']} {r['frozen']}→{r['live']}"
                                    for r in (drifted.get("rows") or [])[:max_rows])))
        else:
            lines.append(f"     живая против замороженной: НЕ ИЗМЕРЕНО — {drifted.get('reason')}")
    for f in (observed(doc, "findings", kind=list) or [])[:max_rows]:
        lines.append(f"     [{str(f.get('severity')).upper()}] {f.get('text')}")
    lines.append("     " + (doc.get("not_reported") or NOT_REPORTED))
    lines.append("     " + (doc.get("advisory") or ADVISORY))
    return lines


def _n(container: Any, key: str) -> Any:
    if not isinstance(container, dict) or key not in container or container[key] is None:
        return "НЕ ИЗМЕРЕНО"
    return container[key]


def format_report(doc: dict, max_rows: int = 16) -> list[str]:
    return [f"— свежесть поверхности §49 приказа «Portfolio CIO» ({ADR}) —"] + report(doc, max_rows)


# ─────────────────────────── CLI ───────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="§49 ТЗ CIO второй осью: свежа ли поверхность приёмки (ADR-994)")
    ap.add_argument("--root", default=os.environ.get("SPA_ROOT") or None,
                    help="корень дерева с конституцией и карточкой (умолчание — своё)")
    ap.add_argument("--data-dir", default=None,
                    help="каталог артефактов; из worktree живого data/ нет — передавать прод")
    ap.add_argument("--rollup-json", default=None,
                    help="JSON живой сводки (`cio_acceptance_rollup --json`) для оси дрейфа")
    ap.add_argument("--live", action="store_true",
                    help="снять живую сводку самому (≈76 с) вместо `--rollup-json`")
    ap.add_argument("--no-write", action="store_true", help="не писать артефакт")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    args = ap.parse_args(argv)
    try:
        doc = run(root=args.root, data_dir=args.data_dir, write=not args.no_write,
                  rollup_json=args.rollup_json, live=args.live)
    except Unmeasured as exc:
        print(f"s49_surface_freshness: НЕ ИЗМЕРЕНО — {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for line in format_report(doc):
            print(line)
    return 1 if doc["counts"]["critical"] or doc["counts"]["warn"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
