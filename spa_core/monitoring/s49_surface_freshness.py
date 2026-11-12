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

## Четвёртый вопрос (ADR-995, цикл #1114): КТО написал вход

ADR-994 сам назвал щель: «самый свежий файл мог написать и ДРУГОЙ,
необъявленный писатель (класс ADR-811)». Замер 12.11 показал, что это не
оговорка, а состояние: `data/decision_audit_trail.json` 05:52Z написала РУКА
сессии (цикл #1106, `--root <прод>` сразу после правки модуля — запись об этом
есть в журнале объявлений `data/session_changes.jsonl` за 65 с до файла), а
прибор v1 засчитал этот файл выключенному бегуну и напечатал «молчит 11 ч» там,
где бегун молчит с 29.10. Кандидат ADR-994 § 6а (проба `Auditability` в
`card_acceptance` пишет артефакт) опровергнут кодом: проба читает артефакт и
зовёт `criterion_verdict`, `run()` прибора не трогает — контроль в батарее.

4. **Кто написал каждый вход?** Боковой канал — журнал объявлений сессий
   (`session_changes.jsonl` в каталоге данных, ВХОД `--session-log` /
   `session_entries=`): запись в окне ±30 мин от `generated_at`, чьи `files`
   или `summary` называют модуль-производитель входа (одна дверь —
   `findings_bridge.CENSUS_PRODUCT`) или сам артефакт, ⇒ `hand` с названной
   сессией. Записи нет ⇒ `unattributed` — писатель НЕ НАЗВАН (ни рука, ни
   бегун), и рядом печатается размер кучи: сколько входов написано в пределах
   ±15 мин (форма прогона моста) — одиночный файл и куча из одиннадцати суть
   разные подозреваемые. Канала нет ⇒ `UNCHECKED` на всю ось, а не «рук нет».
   Молчание производителя теперь печатается ДВАЖДЫ: по любому файлу (нижняя
   граница, как в v1) и БЕЗ рук — и второе честнее о бегуне.

## Чего прибор НЕ докладывает

* Верна ли живая проба — это держит её контроль в обе стороны
  (`.claude/rules/acceptance.md`, п. 3), не этот прибор.
* Почему бегун выключен — у этого вопроса своя карточка; здесь измеряется
  только, ЧТО от его молчания видит поверхность.
* Ничего не чинит и не включает: ADVISORY, читает конституцию, артефакты и
  список флота; `landing/**`, RiskPolicy, стоп-кран, аллокатор не трогаются.
* Кто написал кучу без записи в журнале сессий (03.11 01:06Z — одиннадцать
  файлов формы моста, ни одной записи): боковой канал видит только то, что
  сессия ОБЪЯВИЛА. Штампа писателя в самих артефактах нет (ADR-822/823 — у
  штампа не было читателя); этот прибор и есть первый читатель, и читает он
  канал, а не штамп.

## Коды возврата

* **0** — замер состоялся, поверхность свежа (находок critical нет).
* **1** — замер состоялся и есть находка (входы протухли · производитель не
  загружен · сводка расходится с живой).
* **2** — замера НЕТ ВОВСЕ (конституция или население §49 не прочитаны).

## ADR-996 (цикл #1115): второй канал оси «кто написал» и длительность записи

ADR-995 оставил двенадцать входов с писателем «НЕ НАЗВАН» — две кучи формы моста
(29.10 09:53–10:18Z и 03.11 01:05–01:07Z). Замер #1115 назвал обе ДРУГИМИ каналами:

* **03.11** — сэмплер ступеней `findings_bridge --run` мандата ARB 02 (P1.2) на
  ЖИВОМ прод-`data/`: длительности его отчёта (`decision_reproducibility` 31 с,
  `ranking_tie_persistence` 51 с) равны `mtime − generated_at` ровно у этих двух
  файлов (01:05:36 → 01:06:07; 01:06:08 → 01:06:59), порядок записи равен порядку
  ступеней моста, коммиты мандата легли в 01:08Z, его «замороженная копия data/»
  снята в ~01:55Z — ПОСЛЕ. `SPA_SANDBOX=1` защищал трекер, не `data/`. Рука, не бегун.
* **29.10** — окно отчёта самого моста (`findings_bridge_report.json`:
  `run_started_at` 07:49Z … `generated_at` 10:18Z) накрывает все входы кучи: это
  прогон моста. Зовущего отчёт не называет — штампа `invoked_by` у него нет (ADR-822).

Отсюда два входа прибора: **отчёт моста** как второй канал (вход в его окне —
`bridge_run`, зовущий — штамп или «не назван»; отчёт не прочитан ⇒ канал
`UNCHECKED`, не «прогонов не было») и **`write_lag_s` = mtime − generated_at** у каждой
строки — у ступени моста это длительность ступени, и именно по ней писатель 03.11
был узнан. Рука (ADR-995) сильнее окна: рука, запустившая мост целиком, остаётся рукой.
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

SCHEMA = "s49_surface_freshness/v3"
REPORT_REL = "data/s49_surface_freshness.json"
TALLY_REL = "data/s49_tally_tact.json"
ADR = "ADR-994"
ADR_WRITERS = "ADR-995"
#: Второй канал оси «кто написал» — отчёт самого моста (окно прогона), ADR-996.
ADR_BRIDGE = "ADR-996"

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

#: Исходы оси «кто написал вход» (ADR-995, второй канал — ADR-996). У ОДНОГО
#: входа: `hand` — запись сессии в окне называет модуль-производитель или сам
#: артефакт; `bridge_run` — `generated_at` входа лежит в окне прогона моста по
#: ЕГО СОБСТВЕННОМУ отчёту (`run_started_at` … `generated_at` у
#: `findings_bridge_report.json`): вход написан прогоном моста, а ЗОВУЩИЙ прогона
#: читается из штампа отчёта (`invoked_by`) либо остаётся не назван;
#: `unattributed` — ни то, ни другое, писатель НЕ НАЗВАН (это не «бегун»);
#: `no_clock` — у входа нет `generated_at`, окна не построить. У ОСИ целиком:
#: `measured` / `UNCHECKED` (канал не прочитан — об авторстве не сказано ничего).
#: Порядок: рука сильнее окна — рука, запустившая мост целиком, остаётся рукой.
WRITER_HAND = "hand"
WRITER_BRIDGE_RUN = "bridge_run"
WRITER_UNATTRIBUTED = "unattributed"
WRITER_STATES = (WRITER_HAND, WRITER_BRIDGE_RUN, WRITER_UNATTRIBUTED, NO_CLOCK)
#: Отчёт моста — второй канал: он лежит рядом с артефактами и несёт окно
#: ПОСЛЕДНЕГО прогона. Прогон, снятый до отчёта (сэмплер 03.11 01:05Z, ADR-996),
#: отчёта не оставляет и этим каналом не виден — это сказано в NOT_REPORTED.
BRIDGE_REPORT_NAME = "findings_bridge_report.json"
WRITERS_MEASURED = "measured"
WRITERS_UNCHECKED = "UNCHECKED"
#: Боковой канал — журнал объявлений сессий, живёт рядом с артефактами.
SESSION_LOG_NAME = "session_changes.jsonl"
#: Окно «рука ↔ файл»: в замере 12.11 объявление файлов стояло за 65 с до
#: артефакта, «ДОСТАВЛЕН» — через 146 с после; полчаса покрывают сессию, которая
#: сначала правит, потом гоняет прибор по проду, потом пушит.
HAND_WINDOW_MINUTES = 30.0
#: Куча: входы, написанные в пределах ±15 мин друг от друга, — форма прогона
#: моста. Прогон 29.10 писал тринадцать входов с 09:57:20 по 10:10:16 (13 мин),
#: прогон 03.11 — за 31 с; «в одну секунду» разрезало бы один прогон на кучки.
BATCH_WINDOW_MINUTES = 15.0

OVERALL_OK = "OK"
OVERALL_WARN = "WARN"
OVERALL_CRITICAL = "CRITICAL"
OVERALL_UNCHECKED = "UNCHECKED"

ADVISORY = ("ADVISORY: прибор только ЧИТАЕТ конституцию, артефакты и список флота; "
            "ничего не включает, не пишет в чужие артефакты, не трогает RiskPolicy, "
            "стоп-кран, аллокатор, живой трек и landing/**")

NOT_REPORTED = ("НЕ ДОКЛАДЫВАЕТ: верна ли живая проба (её держит контроль в обе стороны) · "
                "почему бегун выключен (своя карточка) · зовущего вне состава ступеней · "
                "писателя, который НЕ объявил себя в журнале сессий (канал видит только объявленное) · "
                "прогон моста, снятый ДО своего отчёта (окна прогона у него нет) · "
                "зовущего прогона моста, если у отчёта нет штампа `invoked_by`")


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
                  loaded: Optional[set[str]], now: dt.datetime,
                  writers: Optional[dict] = None) -> list[dict]:
    """Производители входов: сколько критериев на каждом, жив ли, когда молчит.

    Молчание измеряется САМЫМ СВЕЖИМ артефактом производителя среди входов:
    «не загружен» говорит о сегодня, «молчит N ч» — с какого момента.

    `writers` (ADR-995) — ось «кто написал»: с ней молчание печатается ВТОРОЙ
    раз, уже БЕЗ входов, написанных рукой сессии (`silent_hours_excluding_hands`).
    Оси нет или она `UNCHECKED` ⇒ `hands_measured=False`, второе число `None` —
    «не измерено», а не «рук не было».
    """
    by_producer: dict[Optional[str], list[dict]] = {}
    for row in inputs:
        if row.get("state") == UNBOUND:
            continue
        producer = producer_of(manifest, row.get("artifact"))
        by_producer.setdefault(producer, []).append(row)

    hands_measured = bool(writers) and writers.get("verdict") == WRITERS_MEASURED
    hand_by_artifact: dict[str, dict] = {}
    if hands_measured:
        for w in writers.get("rows") or ():
            if isinstance(w, dict) and w.get("writer") == WRITER_HAND and w.get("artifact"):
                hand_by_artifact[str(w["artifact"])] = w

    rows: list[dict] = []
    for producer, group in sorted(by_producer.items(), key=lambda kv: str(kv[0])):
        stamped = [(parse_ts(r.get("generated_at")), r.get("artifact")) for r in group]
        stamped = [(s, a) for s, a in stamped if s is not None]
        newest = max(stamped, key=lambda sa: sa[0]) if stamped else None
        last_seen = newest[0].isoformat() if newest else None
        last_seen_artifact = newest[1] if newest else None
        silent_h = round((now - newest[0]).total_seconds() / 3600.0, 2) if newest else None
        hand_written: Optional[int] = None
        last_seen_no_hands: Optional[str] = None
        silent_no_hands: Optional[float] = None
        if hands_measured:
            hand_written = sum(1 for r in group if str(r.get("artifact")) in hand_by_artifact)
            rest = [(s, a) for s, a in stamped if str(a) not in hand_by_artifact]
            newest_rest = max(rest, key=lambda sa: sa[0]) if rest else None
            if newest_rest is not None:
                last_seen_no_hands = newest_rest[0].isoformat()
                silent_no_hands = round((now - newest_rest[0]).total_seconds() / 3600.0, 2)
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
                     "silent_hours": silent_h, "why": why,
                     # ADR-995: тот же вопрос БЕЗ входов, написанных рукой сессии.
                     # `hands_measured=False` ⇒ оба `None` — не измерено, не ноль.
                     "hands_measured": hands_measured,
                     "hand_written": hand_written,
                     "last_seen_excluding_hands": last_seen_no_hands,
                     "silent_hours_excluding_hands": silent_no_hands})
    return rows


# ─────────────────────────── 4. кто написал: боковой канал ───────────────────────────

def module_of(artifact: Optional[str]) -> Optional[str]:
    """Модуль-производитель артефакта — ОДНОЙ дверью, картой ступеней моста.

    Своя карта здесь была бы второй копией правила (ADR-220): мост объявляет,
    какой модуль пишет какой артефакт, и именно его запись сверяется с `files`
    объявления сессии. Артефакта в карте нет ⇒ `None` — рука по модулю не
    распознаётся, остаётся совпадение по самому артефакту.
    """
    if not artifact:
        return None
    try:
        from spa_core.monitoring import findings_bridge as bridge  # noqa: PLC0415
    except ImportError:
        return None
    for entry in (getattr(bridge, "CENSUS_PRODUCT", None) or {}).values():
        if isinstance(entry, dict) and entry.get("artifact") == artifact:
            module = entry.get("module")
            return str(module) if isinstance(module, str) and module else None
    return None


def read_session_log(path: Path) -> tuple[Optional[list[dict]], Optional[str], int]:
    """Записи журнала объявлений; (записи, причина отказа, нечитаемых строк).

    Файла нет или он не читается ⇒ `(None, причина, 0)` — третий исход оси.
    Нечитаемая строка считается и пропускается: журнал пишут много сессий,
    одна битая строка не делает канал несуществующим, но и молчать о ней нельзя.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{path}: {exc.__class__.__name__}: {exc}", 0
    entries: list[dict] = []
    malformed = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if isinstance(doc, dict):
            entries.append(doc)
        else:
            malformed += 1
    return entries, None, malformed


def _names(entry: dict, module: Optional[str], artifact: Optional[str]) -> Optional[str]:
    """Чем запись называет вход: `files` (сильно), `summary` (слабее) или ничем."""
    targets = [t for t in (module, artifact) if t]
    files = entry.get("files")
    if isinstance(files, list):
        for f in files:
            if isinstance(f, str) and any(f.replace("\\", "/").endswith(t) for t in targets):
                return "files"
    summary = entry.get("summary")
    if isinstance(summary, str) and targets:
        stems = {Path(t).stem for t in targets}
        if any(stem and stem in summary for stem in stems):
            return "summary"
    return None


def read_bridge_runs(path: Path) -> tuple[Optional[list[dict]], Optional[str]]:
    """Окна прогонов моста по ЕГО отчёту; (прогоны, причина отказа).

    Отчёт не прочитан ⇒ `(None, причина)` — канал НЕ ПРОЧИТАН (третий исход, не
    «прогонов не было»). Отчёт есть, а часов прогона (`run_started_at` и
    `generated_at`) нет или они не разобраны ⇒ тоже `None` с причиной: окно без
    границ — не окно. Зовущий прогона — штамп `invoked_by` отчёта; штампа нет ⇒
    `caller=None`, и это сказано словами, а не подставлено именем службы.
    """
    doc, problem = read_json(Path(path))
    if doc is None:
        return None, f"отчёт моста {Path(path).name} не прочитан: {problem}"
    if not isinstance(doc, dict):
        return None, f"отчёт моста {Path(path).name}: не словарь"
    start = parse_ts(doc.get("run_started_at"))
    end = parse_ts(doc.get("generated_at"))
    if start is None or end is None:
        return None, (f"у отчёта моста {Path(path).name} нет часов прогона "
                      f"(run_started_at={doc.get('run_started_at')!r}, "
                      f"generated_at={doc.get('generated_at')!r}) — окно не построить")
    if end < start:
        return None, (f"у отчёта моста {Path(path).name} конец прогона раньше начала "
                      f"({end.isoformat()} < {start.isoformat()}) — окно не построить")
    stamp = observed(doc, "invoked_by", kind=dict)
    caller: Optional[str] = None
    if stamp is not None:
        entry = stamp.get("entry") or stamp.get("label") or stamp.get("by")
        caller = str(entry) if isinstance(entry, str) and entry else None
    # Вторая ось штампа (ADR-997): КТО ЗАПУСТИЛ процесс — прямое задание launchd
    # или вложенный прогон. Точка входа у бегуна и у руки одна (`findings_bridge.py`),
    # поэтому зовущий печатается вместе с запуском; записи нет ⇒ слово о ней
    # не печатается вовсе (отсутствие не выдаётся за «вложенный»).
    launcher = observed(doc, "launched_by", kind=dict)
    launcher_text: Optional[str] = None
    if launcher is not None:
        launcher_text = _describe_launcher(launcher)
        if caller is not None:
            caller = f"{caller} · {launcher_text}"
    return [{"source": Path(path).name, "started_at": start.isoformat(),
             "generated_at": end.isoformat(), "caller": caller,
             "launcher": launcher_text,
             "stamp_present": stamp is not None}], None


def _describe_launcher(doc: dict) -> str:
    """Короткая форма записи `launched_by` для строки зовущего (три исхода)."""
    if not doc.get("measured"):
        return f"запуск НЕ ИЗМЕРЕН ({doc.get('reason') or 'причина не названа'})"
    hops = doc.get("hops_to_launchd")
    if doc.get("kind") == "launchd_job":
        return f"прямое задание launchd ({hops} ход(а) до launchd)"
    chain = [c.get("command") for c in (doc.get("chain") or [])[1:] if isinstance(c, dict)]
    head = chain[0] if chain else "—"
    return f"вложенный прогон ({hops} ход(ов) до launchd; над процессом: `{head}`)"


def _written_at(path: Optional[Path]) -> Optional[dt.datetime]:
    """Когда файл реально записан (mtime, UTC); нет пути или файла ⇒ `None`."""
    if path is None:
        return None
    try:
        return dt.datetime.fromtimestamp(os.stat(path).st_mtime, tz=dt.timezone.utc)
    except OSError:
        return None


def _run_covering(runs: list[dict], made: dt.datetime) -> Optional[dict]:
    """Прогон моста, чьё окно [started_at, generated_at] накрывает момент входа."""
    for run in runs:
        start = parse_ts(run.get("started_at"))
        end = parse_ts(run.get("generated_at"))
        if start is not None and end is not None and start <= made <= end:
            return run
    return None


def batch_groups(rows: Iterable[dict], *, batch_minutes: float = BATCH_WINDOW_MINUTES) -> dict[str, list[dict]]:
    """Неатрибутированные входы кучами: соседи ближе `batch_minutes` — одна куча.

    Группа ключуется отметкой ПЕРВОГО входа (до минуты). Резать по календарной
    минуте или часу нельзя: прогон 29.10 шёл с 09:57 по 10:10 и попал бы в два
    часа — две «кучи» из одного прогона.
    """
    stamped = sorted(
        ((parse_ts(r.get("generated_at")), r) for r in rows
         if isinstance(r, dict) and r.get("writer") == WRITER_UNATTRIBUTED
         and (r.get("cluster_size") or 0) > 1 and parse_ts(r.get("generated_at")) is not None),
        key=lambda tr: tr[0])
    groups: dict[str, list[dict]] = {}
    key: Optional[str] = None
    prev: Optional[dt.datetime] = None
    for ts, r in stamped:
        if prev is None or (ts - prev).total_seconds() > float(batch_minutes) * 60.0:
            key = ts.isoformat()[:16]
        groups.setdefault(str(key), []).append(r)
        prev = ts
    return groups


def writer_rows(inputs: Iterable[dict], *, entries: Optional[list[dict]],
                now: dt.datetime, window_minutes: float = HAND_WINDOW_MINUTES,
                batch_minutes: float = BATCH_WINDOW_MINUTES,
                module_of_artifact: Callable[[Optional[str]], Optional[str]] = module_of,
                channel_problem: Optional[str] = None, malformed: int = 0,
                bridge_runs: Optional[list[dict]] = None,
                bridge_problem: Optional[str] = None,
                data_dir: Optional[Path] = None,
                written_at_of: Callable[[Optional[Path]], Optional[dt.datetime]] = _written_at) -> dict:
    """Кто написал каждый вход — по двум боковым каналам.

    Первый канал — журнал объявлений сессий (ADR-995): `entries=None` ⇒ канал НЕ
    ПРОЧИТАН ⇒ вся ось `UNCHECKED` с причиной: о руках не сказано ничего (не «рук
    нет»). Пустой список — канал прочитан, записей нет.

    Второй канал — отчёт самого моста (ADR-996): `bridge_runs=None` ⇒ отчёт НЕ
    ПРОЧИТАН (`bridge_channel.verdict == UNCHECKED`, причина — `bridge_problem`),
    вход в окно прогона не попадает ПО ПОСТРОЕНИЮ и остаётся `unattributed`; пустой
    список — отчёт прочитан, прогонов нет. Вход внутри окна прогона — `bridge_run`,
    зовущий — штамп отчёта или «не назван». Рука сильнее окна.

    `data_dir` — чтобы снять `written_at` (mtime) и `write_lag_s` = mtime −
    `generated_at`: у ступени моста это ДЛИТЕЛЬНОСТЬ ступени (03.11:
    `decision_reproducibility` 31 с, `ranking_tie_persistence` 51 с — ровно числа
    отчёта мандата ARB 02, по которым писатель и был узнан). Нет каталога или файла
    ⇒ `None` — не измерено, не ноль.
    """
    rows_in = [r for r in inputs if r.get("state") != UNBOUND]
    stamps = {id(r): parse_ts(r.get("generated_at")) for r in rows_in}
    bridge_channel = ({"verdict": WRITERS_UNCHECKED, "runs": None, "source": BRIDGE_REPORT_NAME,
                       "reason": bridge_problem or "отчёт моста не читался"}
                      if bridge_runs is None else
                      {"verdict": WRITERS_MEASURED, "runs": list(bridge_runs),
                       "source": BRIDGE_REPORT_NAME, "reason": None})
    if entries is None:
        return {"verdict": WRITERS_UNCHECKED, "window_minutes": window_minutes,
                "batch_minutes": batch_minutes, "entries_read": None,
                "malformed_lines": None, "rows": [],
                "counts": {WRITER_HAND: None, WRITER_BRIDGE_RUN: None,
                           WRITER_UNATTRIBUTED: None, NO_CLOCK: None},
                "bridge_channel": bridge_channel,
                "reason": (f"боковой канал (`{SESSION_LOG_NAME}`) не прочитан — "
                           f"{channel_problem or 'причина не названа'}; об авторстве входов "
                           "не сказано НИЧЕГО")}

    window = dt.timedelta(minutes=float(window_minutes))
    stamped_entries: list[tuple[dt.datetime, dict]] = []
    for e in entries:
        ts = parse_ts(e.get("ts"))
        if ts is not None:
            stamped_entries.append((ts, e))

    out_rows: list[dict] = []
    for r in rows_in:
        made = stamps[id(r)]
        artifact = r.get("artifact")
        row = {"criterion": r.get("criterion"), "artifact": artifact,
               "generated_at": r.get("generated_at"), "module": module_of_artifact(artifact),
               "writer": None, "session": None, "ts": None, "evidence": None,
               "candidates": [], "cluster_size": None, "why": None,
               "written_at": None, "write_lag_s": None,
               "run_started_at": None, "caller": None}
        written = written_at_of(artifact_path(data_dir, str(artifact))
                                if data_dir is not None and artifact else None)
        if written is not None:
            row["written_at"] = written.isoformat()
            if made is not None:
                row["write_lag_s"] = round((written - made).total_seconds(), 1)
        if made is None:
            row["writer"] = NO_CLOCK
            row["why"] = "у входа нет `generated_at` — окно для бокового канала не построить"
            out_rows.append(row)
            continue
        cluster = sum(1 for other in rows_in
                      if stamps[id(other)] is not None
                      and abs((stamps[id(other)] - made).total_seconds()) <= float(batch_minutes) * 60.0)
        row["cluster_size"] = cluster
        in_window = [(ts, e) for ts, e in stamped_entries if abs((ts - made)) <= window]
        hand: Optional[tuple[dt.datetime, dict, str]] = None
        for ts, e in sorted(in_window, key=lambda te: abs((te[0] - made))):
            how = _names(e, row["module"], artifact)
            if how is not None:
                hand = (ts, e, how)
                break
        row["candidates"] = sorted({str(e.get("session")) for _, e in in_window if e.get("session")})
        if hand is not None:
            ts, e, how = hand
            row["writer"] = WRITER_HAND
            row["session"] = str(e.get("session") or "") or None
            row["ts"] = ts.isoformat()
            row["evidence"] = how
            offset = (made - ts).total_seconds()
            row["why"] = (f"сессия {row['session']} объявила в {ts.isoformat()} "
                          f"({'+' if offset >= 0 else '−'}{abs(offset):.0f} с до файла) "
                          f"{'файл модуля' if how == 'files' else 'модуль в тексте'} "
                          f"{row['module'] or artifact}")
        else:
            run = _run_covering(bridge_runs, made) if bridge_runs else None
            if run is not None:
                row["writer"] = WRITER_BRIDGE_RUN
                row["ts"] = run.get("generated_at")
                row["run_started_at"] = run.get("started_at")
                row["evidence"] = "bridge_report"
                row["caller"] = run.get("caller")
                row["why"] = (f"вход написан ПРОГОНОМ моста: окно его отчёта "
                              f"{run.get('started_at')} → {run.get('generated_at')} накрывает "
                              f"{made.isoformat()}; зовущий прогона "
                              + (f"по штампу отчёта: {row['caller']}" if row["caller"]
                                 else "НЕ НАЗВАН — штампа `invoked_by` у отчёта нет"))
            else:
                row["writer"] = WRITER_UNATTRIBUTED
                shape = (f"куча из {cluster} входов в пределах ±{batch_minutes:g} мин — форма прогона моста"
                         if cluster and cluster > 1 else "одиночный файл")
                tail = (f"; в окне ±{window_minutes:g} мин были сессии {', '.join(row['candidates'])}, "
                        "ни одна не называет модуль или артефакт" if row["candidates"]
                        else f"; записей в окне ±{window_minutes:g} мин нет")
                bridge = (f"; отчёт моста не прочитан ({bridge_channel['reason']})"
                          if bridge_runs is None else
                          ("; окно отчёта моста вход не накрывает" if bridge_runs
                           else "; прогонов моста в отчёте нет"))
                lag = (f"; запись длилась {row['write_lag_s']:.0f} с (mtime − generated_at)"
                       if isinstance(row["write_lag_s"], (int, float)) else "")
                row["why"] = f"писатель НЕ НАЗВАН: {shape}{tail}{bridge}{lag}"
        out_rows.append(row)

    counts = {WRITER_HAND: sum(1 for r in out_rows if r["writer"] == WRITER_HAND),
              WRITER_BRIDGE_RUN: sum(1 for r in out_rows if r["writer"] == WRITER_BRIDGE_RUN),
              WRITER_UNATTRIBUTED: sum(1 for r in out_rows if r["writer"] == WRITER_UNATTRIBUTED),
              NO_CLOCK: sum(1 for r in out_rows if r["writer"] == NO_CLOCK)}
    return {"verdict": WRITERS_MEASURED, "window_minutes": window_minutes,
            "batch_minutes": batch_minutes, "entries_read": len(entries),
            "malformed_lines": malformed, "rows": out_rows, "counts": counts,
            "bridge_channel": bridge_channel, "reason": None}


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

def findings(inputs: list[dict], producers: list[dict], tally: dict, drifted: dict,
             writers: Optional[dict] = None) -> list[dict]:
    out: list[dict] = []
    ic = input_counts(inputs)
    bound = len(inputs) - ic[UNBOUND]
    stale_names = [r["criterion"] for r in inputs if r.get("state") == STALE]
    dead = [p for p in producers if p["state"] == NOT_LOADED]
    unmeasured_fleet = [p for p in producers if p["state"] == FLEET_UNMEASURED]
    writers = writers if isinstance(writers, dict) else None
    hands_measured = bool(writers) and writers.get("verdict") == WRITERS_MEASURED

    if ic[STALE] and dead:
        worst = max(dead, key=lambda p: p["criteria_count"])
        if worst.get("silent_hours") is None:
            silent = "молчит, с какого момента — НЕ ИЗМЕРЕНО (часов в артефактах нет)"
        elif worst.get("hands_measured") and (worst.get("hand_written") or 0) > 0:
            # ADR-995: самый свежий файл написала РУКА — нижняя граница молчания
            # бегуна читается по входам БЕЗ рук, и печатаются ОБЕ.
            no_hands = worst.get("silent_hours_excluding_hands")
            silent = (f"самый свежий его продукт {worst['last_seen_artifact']} — "
                      f"{worst['silent_hours']:.0f} ч назад ({worst['last_seen']}), но его "
                      f"написала РУКА сессии, не бегун; без рук "
                      + (f"нижняя граница молчания {no_hands:.0f} ч "
                         f"({worst.get('last_seen_excluding_hands')})"
                         if no_hands is not None else
                         "молчание НЕ ИЗМЕРЕНО — все его входы написаны руками"))
        else:
            silent = (f"самый свежий его продукт {worst['last_seen_artifact']} — "
                      f"{worst['silent_hours']:.0f} ч назад ({worst['last_seen']}; нижняя граница "
                      f"молчания: файл мог написать и необъявленный писатель"
                      + ("" if worst.get("hands_measured") else
                         " — ось «кто написал» не измерена") + ")")
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

    # ─── ADR-995: кто написал входы ───
    if writers is None or writers.get("verdict") != WRITERS_MEASURED:
        out.append({"severity": "unchecked", "key": "writers_unchecked",
                    "text": ("кто написал входы §49 — НЕ ИЗМЕРЕНО: "
                             + (str(writers.get("reason")) if writers else
                                "ось «кто написал» не снималась"))})
    else:
        wrows = [r for r in (writers.get("rows") or []) if isinstance(r, dict)]
        hands = [r for r in wrows if r.get("writer") == WRITER_HAND]
        if hands:
            named = "; ".join(
                f"{r.get('criterion')} ({r.get('artifact')}) — {r.get('session')} "
                f"{r.get('ts')} по {r.get('evidence')}" for r in hands)
            out.append({"severity": "warn", "key": "hand_written",
                        "text": (f"{len(hands)} из {bound} входов §49 написаны РУКОЙ сессии, "
                                 f"а не производителем: {named}; поверхность читает такой файл "
                                 "как продукт бегуна, и его возраст занижает молчание бегуна")})
        dead_names = {p["producer"] for p in dead}
        batches = batch_groups(wrows, batch_minutes=float(writers.get("batch_minutes")
                                                           or BATCH_WINDOW_MINUTES))
        bridge_channel = writers.get("bridge_channel") if isinstance(writers.get("bridge_channel"), dict) else None
        if batches and dead_names:
            def _span(rs: list[dict]) -> str:
                lags = [r.get("write_lag_s") for r in rs if isinstance(r.get("write_lag_s"), (int, float))]
                if not lags:
                    return "длительность записи НЕ ИЗМЕРЕНА"
                return (f"запись длилась {min(lags):.0f}…{max(lags):.0f} с" if len(lags) > 1
                        else f"запись длилась {lags[0]:.0f} с")
            shown = "; ".join(f"{stamp}: {len(rs)} входов ({', '.join(str(r.get('criterion')) for r in rs)}; {_span(rs)})"
                              for stamp, rs in sorted(batches.items()))
            # Третий исход о ЗОВУЩЕМ: каналы не различают «бегун до выключения» и
            # «рука без объявления» — поэтому `unchecked`, а не «рука» и не «бегун».
            # ADR-996: третий спрошенный канал — отчёт моста — назван с его исходом,
            # чтобы «не накрывает» и «не прочитан» не читались одинаково.
            if bridge_channel is None:
                bridge_said = "отчёт моста не спрашивался"
            elif bridge_channel.get("verdict") != WRITERS_MEASURED:
                bridge_said = f"отчёт моста НЕ ПРОЧИТАН ({bridge_channel.get('reason')})"
            elif bridge_channel.get("runs"):
                bridge_said = ("окно отчёта моста ("
                               + ", ".join(f"{r.get('started_at')} → {r.get('generated_at')}"
                                           for r in bridge_channel["runs"])
                               + ") эти входы не накрывает — прогон, их написавший, отчёта не оставил")
            else:
                bridge_said = "в отчёте моста прогонов нет"
            out.append({"severity": "unchecked", "key": "batch_without_a_caller",
                        "text": (f"{sum(len(v) for v in batches.values())} входов §49 написаны кучей "
                                 f"формы моста, производитель сегодня ВЫКЛЮЧЕН, и зовущий НЕ НАЗВАН "
                                 f"ни журналом сессий, ни флотом, ни отчётом моста ({bridge_said}) — "
                                 f"бегун до выключения или рука без объявления, каналы не различают: {shown}")})
        bridge_rows = [r for r in wrows if r.get("writer") == WRITER_BRIDGE_RUN]
        if bridge_rows and dead_names:
            by_run: dict[tuple, list[dict]] = {}
            for r in bridge_rows:
                by_run.setdefault((r.get("run_started_at"), r.get("ts"), r.get("caller")), []).append(r)
            unstamped = {k: v for k, v in by_run.items() if not k[2]}
            stamped = {k: v for k, v in by_run.items() if k[2]}
            if unstamped:
                shown = "; ".join(f"прогон {k[0]} → {k[1]}: {len(v)} входов "
                                  f"({', '.join(str(r.get('criterion')) for r in v)})"
                                  for k, v in sorted(unstamped.items(), key=lambda kv: str(kv[0])))
                # Прогон НАЗВАН окном его отчёта, зовущий — нет: отчёт без штампа
                # (ADR-822 — у штампа не было читателя; теперь есть). «Бегун до
                # выключения» и «рука, запустившая мост целиком» отчётом не различаются.
                out.append({"severity": "unchecked", "key": "bridge_run_without_a_stamp",
                            "text": (f"{sum(len(v) for v in unstamped.values())} входов §49 написаны "
                                     f"ПРОГОНОМ моста (окно — из отчёта моста {BRIDGE_REPORT_NAME}), "
                                     f"производитель сегодня ВЫКЛЮЧЕН, а зовущего прогона отчёт не "
                                     f"называет — штампа `invoked_by` у него нет (бегун до выключения "
                                     f"или рука, запустившая мост целиком, — отчёт не различает): {shown}")})
            if stamped:
                shown = "; ".join(f"прогон {k[0]} → {k[1]} зван {k[2]}: {len(v)} входов"
                                  for k, v in sorted(stamped.items(), key=lambda kv: str(kv[0])))
                out.append({"severity": "info", "key": "bridge_run_caller_named",
                            "text": (f"{sum(len(v) for v in stamped.values())} входов §49 написаны "
                                     f"прогоном моста, и его зовущий назван штампом отчёта: {shown}")})
        if not hands and not (batches and dead_names) and not (bridge_rows and dead_names):
            out.append({"severity": "info", "key": "no_hands",
                        "text": (f"рук среди {bound} входов §49 не найдено (журнал сессий: "
                                 f"{writers.get('entries_read')} записей, окно "
                                 f"±{writers.get('window_minutes'):g} мин)")})

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
            live_rows: Optional[list[dict]] = None, ref: str = "origin/main",
            session_entries: Optional[list[dict]] = None,
            session_log: str | Path | None = None,
            window_minutes: float = HAND_WINDOW_MINUTES,
            bridge_runs: Optional[list[dict]] = None,
            bridge_report: str | Path | None = None) -> dict:
    """Снять четыре оси. Часы, флот, живые строки, журнал сессий и отчёт моста — ВХОДЫ.

    `bridge_runs` (ADR-996): `None` — прочитать отчёт моста самому (`bridge_report`,
    умолчание — `findings_bridge_report.json` рядом с артефактами; не прочитан ⇒
    второй канал оси `UNCHECKED` с причиной); список — окна прогонов даны контролем,
    пустой список = «отчёт прочитан, прогонов нет».

    `loaded=None` при `fleet_asked=False` означает «спросить флот самому»; при
    `fleet_asked=True` — «спросили, ответа нет» (третий исход). Контроль
    подменяет оба явно, чтобы ни одна сцена не упиралась в живой `launchctl`.

    `session_entries` (ADR-995): `None` — прочитать журнал самому (`session_log`,
    умолчание — `session_changes.jsonl` рядом с артефактами; не прочитан ⇒ ось
    `UNCHECKED`); список — записи даны контролем, пустой список = «канал прочитан,
    записей нет» (измерение, не третий исход).
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
    channel_problem: Optional[str] = None
    malformed = 0
    log_path = Path(session_log) if session_log else data / SESSION_LOG_NAME
    if session_entries is None:
        session_entries, channel_problem, malformed = read_session_log(log_path)
    bridge_problem: Optional[str] = None
    bridge_path = Path(bridge_report) if bridge_report else data / BRIDGE_REPORT_NAME
    if bridge_runs is None:
        bridge_runs, bridge_problem = read_bridge_runs(bridge_path)
    writers = writer_rows(inputs, entries=session_entries, now=moment,
                          window_minutes=window_minutes, channel_problem=channel_problem,
                          malformed=malformed, bridge_runs=bridge_runs,
                          bridge_problem=bridge_problem, data_dir=data)
    writers["session_log"] = str(log_path)
    writers["bridge_channel"]["path"] = str(bridge_path)
    producers = producer_rows(inputs, manifest=manifest, loaded=loaded, now=moment,
                              writers=writers)
    tally = tally_state(data, manifest=manifest, now=moment)
    drifted = drift(tally["rows"], live_rows)
    found = findings(inputs, producers, tally, drifted, writers)
    counts = {s: sum(1 for f in found if f["severity"] == s)
              for s in ("critical", "warn", "info", "unchecked")}
    return {
        "schema": SCHEMA,
        "adr": ADR,
        "adr_writers": ADR_WRITERS,
        "adr_bridge_channel": ADR_BRIDGE,
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
        "writers": writers,
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
        rollup_json: str | Path | None = None, live: bool = False,
        session_log: str | Path | None = None, **kw) -> dict:
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
    doc = measure(root_path, data_dir=data_dir, now=now, live_rows=live_rows,
                  session_log=session_log, **kw)
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
        if p.get("hands_measured"):
            no_hands = p.get("silent_hours_excluding_hands")
            silent += (f" по любому файлу · без рук {no_hands:.0f} ч"
                       if isinstance(no_hands, (int, float)) else
                       " по любому файлу · без рук НЕ ИЗМЕРЕНО")
            silent += f" (рукой {p.get('hand_written')})"
        else:
            silent += " (кто писал — НЕ ИЗМЕРЕНО)"
        lines.append(f"     [{p.get('state')}] {p.get('producer')}: критериев "
                     f"{p.get('criteria_count')}, протухло {p.get('stale_count')}, {silent}")
    writers = observed(doc, "writers", kind=dict)
    if writers is None:
        lines.append("     кто написал входы: НЕ ИЗМЕРЕНО — оси нет в артефакте (схема v1)")
    elif writers.get("verdict") == WRITERS_MEASURED:
        wc = observed(writers, "counts", kind=dict)
        lines.append(f"     кто написал входы ({ADR_WRITERS}/{ADR_BRIDGE}): рукой {_n(wc, WRITER_HAND)} · "
                     f"прогоном моста {_n(wc, WRITER_BRIDGE_RUN)} · не назван "
                     f"{_n(wc, WRITER_UNATTRIBUTED)} · без часов {_n(wc, NO_CLOCK)} "
                     f"(журнал сессий: записей {writers.get('entries_read')}, нечитаемых "
                     f"{writers.get('malformed_lines')}, окно ±{writers.get('window_minutes')} мин)")
        bc = observed(writers, "bridge_channel", kind=dict)
        if bc is None:
            lines.append("       отчёт моста: НЕ СПРАШИВАЛСЯ (канала нет в артефакте — схема v2)")
        elif bc.get("verdict") != WRITERS_MEASURED:
            lines.append(f"       отчёт моста: НЕ ПРОЧИТАН — {bc.get('reason')}")
        else:
            runs = bc.get("runs") or []
            lines.append(f"       отчёт моста ({bc.get('source')}): прогонов {len(runs)}"
                         + "".join(f" · {r.get('started_at')} → {r.get('generated_at')}, зовущий "
                                   f"{r.get('caller') or 'НЕ НАЗВАН (штампа нет)'}" for r in runs))
        for r in (observed(writers, "rows", kind=list) or [])[:max_rows]:
            if r.get("writer") == WRITER_HAND:
                lines.append(f"       [hand] {r.get('criterion')} {r.get('artifact')}: {r.get('why')}")
            elif r.get("writer") == WRITER_BRIDGE_RUN:
                lines.append(f"       [bridge_run] {r.get('criterion')} {r.get('artifact')}: {r.get('why')}")
    else:
        lines.append(f"     кто написал входы ({ADR_WRITERS}): НЕ ИЗМЕРЕНО — {writers.get('reason')}")
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
    ap.add_argument("--session-log", default=None,
                    help=f"журнал объявлений сессий для оси «кто написал» (ADR-995); умолчание — "
                         f"{SESSION_LOG_NAME} рядом с артефактами; не прочитан ⇒ ось UNCHECKED")
    ap.add_argument("--bridge-report", default=None,
                    help=f"отчёт моста для второго канала оси «кто написал» (ADR-996); умолчание — "
                         f"{BRIDGE_REPORT_NAME} рядом с артефактами; не прочитан ⇒ канал UNCHECKED")
    ap.add_argument("--no-write", action="store_true", help="не писать артефакт")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    args = ap.parse_args(argv)
    try:
        doc = run(root=args.root, data_dir=args.data_dir, write=not args.no_write,
                  rollup_json=args.rollup_json, live=args.live, session_log=args.session_log,
                  bridge_report=args.bridge_report)
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
