"""Сколько снимков в день видит запись решения — и один ли это выбор (заказ #550/#551).

Заказ цикла #550 (ADR-312), подтверждённый #551, поставил вопрос так: **сколько
снимков в день видит запись — и один ли это выбор?** Оркестратор 08.09 произвёл
три снимка (06:00, 10:41, 17:27), а запись за день одна. Делается ли она по
расписанию и берёт последний снимок, или её момент сам плавает — и совпадает ли
он с моментом, на котором аллокатор считал цель?

**Ловушка названа заказом заранее и здесь ИЗМЕРЕНА, а не обойдена.**
``generated_at`` записи и ``generated_at`` снимка суть отметки РАЗНЫХ
производителей, и «запись новее снимка» НЕ означает «запись видела этот снимок».
Замер #550 прямо показывал обратный порядок (запись 07:59:42, снимок 07:59:45).
Прибор не пытается чинить это осторожностью — он спрашивает у носителя, КАКОЙ
ПРОГОН произвёл запись, и меряет знак разницы.

## Три поверхности, и у них разные ответы

1. **Опознание прогона.** ``audit_trail.jsonl`` несёт ``correlation_id`` —
   идентичность прогона — и событие ``cycle_start``. Запись опознаётся по
   близости своей отметки к ``cycle_start`` (окно :data:`PAIR_TOLERANCE_S`), то
   есть по ТОЖДЕСТВУ ПРОГОНА, а не по соседству отметок с чужим артефактом.
   Кандидатов ноль ⇒ ``unidentified_no_start_within_tolerance``; кандидатов два
   и больше ⇒ ``ambiguous_multiple_starts``; носителя за день нет вовсе ⇒
   ``unmeasured_no_run_carrier``. Ни один из трёх не есть «не совпало».

2. **Опознание снимка ПО ЗНАЧЕНИЮ, а не по времени.** Для каждой ноги записи
   ищется снимок дня, чья наблюдённая ставка РАВНА записанной
   (``apy_composition_log.jsonl`` — двусторонний носитель, пишет строку на
   каждое наблюдение и несёт отметку снимка отдельно от отметки прогона).
   Совпали ноги, и все указывают на ОДИН снимок ⇒ ``single_snapshot``; указывают
   на РАЗНЫЕ ⇒ ``mixed_snapshots`` (запись склеена из нескольких снимков — это
   находка, а не норма); одно и то же значение лежит в двух снимках ⇒ нога
   ``ambiguous_value`` и никого не опознаёт (ставка не двигалась, и молчание
   носителя тут не есть свидетельство); не совпала ни одна ⇒
   ``unidentified_no_value_match``.

   ⚠️ Границу надо назвать вслух: ``apy`` носителя — величина рода
   ``hint_winner`` (ставка пула-победителя), а ``apy_evidenced_pct`` записи —
   ставка протокола. Что это ОДНА величина, прибор не утверждает; поэтому
   несовпадение объявляется третьим исходом, а НЕ дырой транскрипции. Работает
   только положительная сторона: одновременное точное совпадение нескольких ног
   на ОДНОМ снимке опознаёт его, несовпадение не опровергает ничего.

3. **Замена строки дня.** Писатель журнала заменяет строку той же даты на каждом
   повторном прогоне (его собственный докстринг: «Same-date line is REPLACED
   (latest run of the day wins)»). Значит «один снимок в день» есть не правило
   отбора, а исход гонки: выживает тот прогон, что отработал ПОСЛЕДНИМ. Прибор
   меряет, сколько прогонов было в дне и каким по счёту оказался выживший.

## Чего прибор НЕ докладывает — и почему это третий исход, а не ноль

**Сколько РАЗНЫХ теневых целей затёрто — НЕ ИЗМЕРЕНО, и измерено быть не может
имеющимися носителями:** единственным носителем теневой цели прогона была та
самая строка, которую замена и уничтожила. Нижняя граница движения входов дня
берётся у ДРУГОГО производителя — ``target_usd`` события
``allocation_proposal`` (живой аллокатор, не тень), и она объявляется чужой
величиной явно, а не выдаётся за теневую.

**ADVISORY.** Прибор ничего не чинит и не предлагает чинить молча: ни писатель
журнала решений, ни ``POLLED_ADAPTERS``, ни пины, ни частота опроса, ни
``TriggerParams``, ни ``MIN_HIT_RATE``, ни пороги RiskPolicy v1.0, ни стоп-кран,
ни живой трек не трогаются, капитал не двигается. Живое ``data/`` открывается на
запись ровно один раз — для собственного артефакта.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("spa.monitoring.decision_record_run_identity")

VERSION = "decision-record-run-identity-v1"
OUTPUT_FILENAME = "decision_record_run_identity.json"
SCHEMA = "decision-record-run-identity/1.0"

HISTORY_FILENAME = "allocation_rationale_history.jsonl"
AUDIT_FILENAME = "audit_trail.jsonl"
COMPOSITION_FILENAME = "apy_composition_log.jsonl"
SNAPSHOT_FILENAME = "adapter_orchestrator_status.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Окно опознания прогона по отметке ``cycle_start``. Замер 10.09 на 19 днях:
#: |Δ| ≤ 0.134 с, медиана 0.002 с — то есть окно шире наблюдённого разброса на
#: порядок, и всё равно уже любого межпрогонного зазора (ближайшие соседние
#: прогоны дня отстоят на минуты). Граница ВКЛЮЧАЮЩАЯ: ровно ``PAIR_TOLERANCE_S``
#: считается опознанием.
PAIR_TOLERANCE_S = 1.0

#: Ставки сравниваются ОКРУГЛЁННЫМИ до :data:`VALUE_ROUND` знаков — в этом виде
#: их пишут оба производителя. Сетка сравнения поэтому и есть единица последнего
#: разряда, а не отдельный допуск: `round()` двух десятично равных чисел даёт
#: один и тот же double, и «почти равно» здесь означало бы «равно после
#: округления», то есть ту же проверку словами. Отдельная константа-эпсилон была
#: бы границей, НЕДОСТИЖИМОЙ по построению (замер батареи #552: мутация её знака
#: сравнения не краснеет ни на одном входе), — то есть украшением.
VALUE_ROUND = 4

#: День считается затёртым, когда прогонов ДВА и больше. Граница ВКЛЮЧАЮЩАЯ.
MIN_RUNS_FOR_REPLACEMENT = 2

EVENT_CYCLE_START = "cycle_start"
EVENT_PROPOSAL = "allocation_proposal"

#: Вердикты опознания прогона.
RUN_IDENTIFIED = "identified"
RUN_NO_START = "unidentified_no_start_within_tolerance"
RUN_AMBIGUOUS = "ambiguous_multiple_starts"
RUN_NO_CARRIER = "unmeasured_no_run_carrier"

#: Вердикты опознания снимка по значению.
SNAP_SINGLE = "single_snapshot"
SNAP_MIXED = "mixed_snapshots"
SNAP_NO_MATCH = "unidentified_no_value_match"
SNAP_NO_CARRIER = "unmeasured_no_snapshot_carrier"

#: Положение выжившего прогона среди прогонов дня.
POS_LAST = "last"
POS_FIRST = "first"
POS_MIDDLE = "middle"
POS_ONLY = "only"

#: Ориентация отметки записи относительно отметки её СОБСТВЕННОГО прогона.
ORIENT_RECORD_EARLIER = "record_earlier_than_own_run"
ORIENT_RECORD_LATER = "record_later_than_own_run"
ORIENT_EQUAL = "equal"


def _is_finite(x) -> bool:
    """Конечное число и НЕ bool (``True`` — это 1, и она бы прошла как ставка)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    return x == x and x not in (float("inf"), float("-inf"))


def _parse_ts(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read_jsonl(path: Path) -> Tuple[List[dict], Optional[str]]:
    """Строки JSONL. Нечитаемая строка ПРОПУСКАЕТСЯ, а не роняет замер."""
    if not path.exists():
        return [], f"нет файла {path.name}"
    out: List[dict] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        return [], f"{path.name} не читается: {exc}"
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out, None


def _read_json(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    if not path.exists():
        return None, f"нет файла {path.name}"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # noqa: BLE001
        return None, f"{path.name} не читается: {exc}"
    return (obj if isinstance(obj, dict) else None), None


def run_index(audit_rows: Sequence[dict]) -> Dict[str, Dict[str, dict]]:
    """``день -> correlation_id -> {start, proposals: [ts], targets: [ключ]}``.

    Прогон существует для прибора только когда у него есть ``cycle_start``:
    именно с этой отметкой сверяется запись, и прогон без неё опознать нечем.
    День берётся у ``cycle_start``, а не у каждого события, — иначе прогон,
    перешагнувший полночь, попал бы в оба дня и удвоил население.
    """
    starts: Dict[str, Tuple[str, datetime]] = {}
    for row in audit_rows:
        if row.get("event_type") != EVENT_CYCLE_START:
            continue
        corr = row.get("correlation_id")
        ts = _parse_ts(row.get("timestamp"))
        if not isinstance(corr, str) or not corr or ts is None:
            continue
        # Повторный cycle_start у одного correlation_id — берём самый ранний.
        prev = starts.get(corr)
        if prev is None or ts < prev[1]:
            starts[corr] = (str(row.get("timestamp")), ts)

    index: Dict[str, Dict[str, dict]] = {}
    for corr, (raw_ts, ts) in starts.items():
        day = raw_ts[:10]
        index.setdefault(day, {})[corr] = {
            "correlation_id": corr,
            "cycle_start": raw_ts,
            "_start_dt": ts,
            "proposals": [],
            "targets": [],
        }

    by_corr = {corr: day for day, runs in index.items() for corr in runs}
    for row in audit_rows:
        if row.get("event_type") != EVENT_PROPOSAL:
            continue
        corr = row.get("correlation_id")
        day = by_corr.get(corr) if isinstance(corr, str) else None
        if day is None:
            continue
        entry = index[day][corr]
        entry["proposals"].append(row.get("timestamp"))
        target = (row.get("data") or {}).get("target_usd")
        if isinstance(target, dict):
            entry["targets"].append(json.dumps(
                {k: round(float(v), 2) for k, v in sorted(target.items())
                 if _is_finite(v)}, sort_keys=True))
    return index


def observation_index(rows: Sequence[dict]) -> Dict[Tuple[str, str], Dict[str, float]]:
    """``(день, адаптер) -> {снимок: ставка}`` из двустороннего носителя."""
    out: Dict[Tuple[str, str], Dict[str, float]] = {}
    for row in rows:
        snap = row.get("snapshot")
        adapter = row.get("adapter")
        apy = row.get("apy")
        if not isinstance(snap, str) or not snap or not isinstance(adapter, str):
            continue
        if not _is_finite(apy):
            continue
        out.setdefault((snap[:10], adapter), {})[snap] = round(float(apy), VALUE_ROUND)
    return out


def identify_run(record: dict, day_runs: Dict[str, dict]) -> dict:
    """Какой прогон произвёл эту запись — по ТОЖДЕСТВУ прогона, не по соседству.

    Возвращает вердикт, опознанный прогон (если один), знак и величину разницы
    отметок. Знак — не украшение: он и есть ответ на ловушку заказа.
    """
    stamp = _parse_ts(record.get("generated_at"))
    if stamp is None:
        return {"verdict": RUN_NO_CARRIER, "why": "у записи нет разбираемой отметки"}
    if not day_runs:
        return {"verdict": RUN_NO_CARRIER, "why": "за день нет ни одного cycle_start"}

    ordered = sorted(day_runs.values(), key=lambda r: r["_start_dt"])
    hits = [(i, r) for i, r in enumerate(ordered)
            if abs((r["_start_dt"] - stamp).total_seconds()) <= PAIR_TOLERANCE_S]
    if not hits:
        nearest = min(ordered,
                      key=lambda r: abs((r["_start_dt"] - stamp).total_seconds()))
        return {
            "verdict": RUN_NO_START,
            "runs_that_day": len(ordered),
            "nearest_delta_s": round(
                (nearest["_start_dt"] - stamp).total_seconds(), 3),
        }
    if len(hits) > 1:
        return {"verdict": RUN_AMBIGUOUS, "runs_that_day": len(ordered),
                "candidates": len(hits)}

    pos_i, run = hits[0]
    delta = round((run["_start_dt"] - stamp).total_seconds(), 3)
    n = len(ordered)
    if n == 1:
        position = POS_ONLY
    elif pos_i == n - 1:
        position = POS_LAST
    elif pos_i == 0:
        position = POS_FIRST
    else:
        position = POS_MIDDLE
    if delta > 0:
        orientation = ORIENT_RECORD_EARLIER
    elif delta < 0:
        orientation = ORIENT_RECORD_LATER
    else:
        orientation = ORIENT_EQUAL
    return {
        "verdict": RUN_IDENTIFIED,
        "correlation_id": run["correlation_id"],
        "cycle_start": run["cycle_start"],
        "delta_to_cycle_start_s": delta,
        "orientation": orientation,
        "runs_that_day": n,
        "position": position,
        "distinct_targets_that_day": len({t for r in ordered for t in r["targets"]}),
        "proposal_after_record": sum(
            1 for p in run["proposals"]
            if (_parse_ts(p) or stamp) > stamp),
        "proposals_in_run": len(run["proposals"]),
    }


def identify_snapshot(record: dict,
                      obs: Dict[Tuple[str, str], Dict[str, float]]) -> dict:
    """Какой снимок видела запись — по ТОЖДЕСТВУ ЗНАЧЕНИЯ, не по времени.

    Работает только положительная сторона совпадения: одновременное точное
    совпадение ног опознаёт снимок, несовпадение НЕ опровергает ничего (рода
    величин у носителя и у записи разные, см. модульный докстринг).
    """
    day = record.get("cycle_date")
    evidenced = record.get("apy_evidenced_pct")
    if not isinstance(day, str) or not isinstance(evidenced, dict):
        return {"verdict": SNAP_NO_CARRIER, "why": "запись без даты или без ставок"}

    day_snapshots = sorted({s for (d, _leg), m in obs.items() if d == day
                            for s in m})
    if not day_snapshots:
        return {"verdict": SNAP_NO_CARRIER,
                "why": "за день носитель не знает ни одного снимка"}

    legs_matched: Dict[str, str] = {}
    ambiguous: List[str] = []
    unmatched: List[str] = []
    for leg, value in sorted(evidenced.items()):
        seen = obs.get((day, leg))
        if not seen:
            unmatched.append(leg)
            continue
        if not _is_finite(value):
            unmatched.append(leg)
            continue
        target = round(float(value), VALUE_ROUND)
        hits = [s for s, v in sorted(seen.items()) if v == target]
        if len(hits) == 1:
            legs_matched[leg] = hits[0]
        elif len(hits) > 1:
            # Значение не двигалось между снимками — оно никого не опознаёт.
            ambiguous.append(leg)
        else:
            unmatched.append(leg)

    base = {
        "snapshots_known_that_day": len(day_snapshots),
        "snapshots_known": day_snapshots,
        "legs_matched": len(legs_matched),
        "legs_ambiguous_value": len(ambiguous),
        "legs_unmatched": len(unmatched),
    }
    if not legs_matched:
        base["verdict"] = SNAP_NO_MATCH
        return base
    pointed = sorted(set(legs_matched.values()))
    base["snapshots_pointed_to"] = pointed
    base["verdict"] = SNAP_SINGLE if len(pointed) == 1 else SNAP_MIXED
    if len(pointed) == 1:
        base["snapshot"] = pointed[0]
        base["snapshot_is_last_known"] = (pointed[0] == day_snapshots[-1])
    return base


def snapshot_orientation(snapshot: Optional[dict], record: dict) -> dict:
    """Живой (перезаписываемый) снимок против отметки записи ТОГО ЖЕ дня.

    Носитель перезаписывается каждым прогоном, поэтому он свидетельствует
    только о СВОЁМ дне и только пока не ушёл вперёд по дате. Совпадение ставок
    проверяется по значению; знак разницы отметок — отдельно, потому что именно
    он и есть предмет ловушки.
    """
    if not isinstance(snapshot, dict):
        return {"verdict": "unmeasured_no_live_snapshot"}
    snap_ts = _parse_ts(snapshot.get("generated_at"))
    rec_ts = _parse_ts(record.get("generated_at"))
    if snap_ts is None or rec_ts is None:
        return {"verdict": "unmeasured_no_stamp"}
    if snapshot.get("generated_at", "")[:10] != str(record.get("cycle_date")):
        return {"verdict": "unmeasured_different_day"}

    evidenced = record.get("apy_evidenced_pct") or {}
    adapters = snapshot.get("adapters")
    same = differ = 0
    if isinstance(adapters, list):
        for entry in adapters:
            if not isinstance(entry, dict):
                continue
            name = entry.get("protocol")
            apy = entry.get("apy_pct")
            value = evidenced.get(name)
            if not _is_finite(apy) or not _is_finite(value):
                continue
            if round(float(apy), VALUE_ROUND) == round(float(value), VALUE_ROUND):
                same += 1
            else:
                differ += 1
    delta = round((snap_ts - rec_ts).total_seconds(), 3)
    return {
        "verdict": "measured",
        "legs_equal": same,
        "legs_differ": differ,
        "snapshot_minus_record_s": delta,
        "snapshot_newer_than_record": delta > 0,
    }


def measure(data_dir, *, now: Optional[datetime] = None) -> dict:
    """Полный замер. Часы — ВХОД (``now``), а не окружение."""
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)

    history, hist_why = _read_jsonl(data_dir / HISTORY_FILENAME)
    audit, _audit_why = _read_jsonl(data_dir / AUDIT_FILENAME)
    comp, _comp_why = _read_jsonl(data_dir / COMPOSITION_FILENAME)
    live_snapshot, _snap_why = _read_json(data_dir / SNAPSHOT_FILENAME)

    doc: dict = {
        "schema": SCHEMA,
        "version": VERSION,
        "generated_at": now.isoformat(),
        "status": STATUS_UNMEASURED,
        "journal_rows": len(history),
        # `days`/`population` объявлены ОБЯЗАТЕЛЬНЫМИ в схеме шага 0-офис, поэтому
        # они существуют и на пустом входе: артефакт, потерявший ключ, читался бы
        # как «поле не заполнено», а не как «мерить было нечего».
        "days": [],
        "population": _population([]),
        "findings": [],
        "advisory": ("писатель журнала решений, POLLED_ADAPTERS, пины, частота "
                     "опроса, TriggerParams, MIN_HIT_RATE, пороги RiskPolicy "
                     "v1.0, стоп-кран и живой трек НЕ трогаются — прибор только "
                     "называет, что видит запись и какой прогон её пережил"),
        "does_not_report": (
            "сколько РАЗНЫХ ТЕНЕВЫХ целей затёрто заменой строки дня — "
            "единственным носителем теневой цели прогона была та самая строка, "
            "которую замена и уничтожила; нижняя граница движения входов дня "
            "взята у ДРУГОГО производителя (target_usd живого аллокатора) и "
            "теневой величиной не является"),
    }
    if not history:
        doc["why_unmeasured"] = hist_why or "журнал решений пуст"
        return doc

    runs = run_index(audit)
    obs = observation_index(comp)

    days: List[dict] = []
    for record in history:
        day = record.get("cycle_date")
        entry = {
            "cycle_date": day,
            "record_generated_at": record.get("generated_at"),
            "run": identify_run(record, runs.get(str(day)) or {}),
            "snapshot": identify_snapshot(record, obs),
        }
        orientation = snapshot_orientation(live_snapshot, record)
        if orientation.get("verdict") == "measured":
            entry["live_snapshot"] = orientation
        days.append(entry)

    doc["days"] = days
    doc["population"] = _population(days)
    doc["findings"] = _findings(doc["population"], days)
    doc["status"] = _status(doc["population"], doc["findings"])
    return doc


def _population(days: Sequence[dict]) -> dict:
    run_counts: Dict[str, int] = {}
    snap_counts: Dict[str, int] = {}
    positions: Dict[str, int] = {}
    orientations: Dict[str, int] = {}
    replaced_runs = 0
    replaced_days = 0
    hidden_distinct_targets = 0
    for entry in days:
        r = entry["run"]
        run_counts[r["verdict"]] = run_counts.get(r["verdict"], 0) + 1
        s = entry["snapshot"]
        snap_counts[s["verdict"]] = snap_counts.get(s["verdict"], 0) + 1
        if r["verdict"] != RUN_IDENTIFIED:
            continue
        positions[r["position"]] = positions.get(r["position"], 0) + 1
        orientations[r["orientation"]] = orientations.get(r["orientation"], 0) + 1
        n = r["runs_that_day"]
        if n >= MIN_RUNS_FOR_REPLACEMENT:
            replaced_days += 1
            replaced_runs += n - 1
            hidden_distinct_targets += max(0, r["distinct_targets_that_day"] - 1)
    return {
        "journal_days": len(days),
        "run_verdicts": run_counts,
        "snapshot_verdicts": snap_counts,
        "positions": positions,
        "orientations": orientations,
        "days_with_replacement": replaced_days,
        "runs_not_in_journal": replaced_runs,
        "hidden_distinct_live_targets": hidden_distinct_targets,
    }


def _findings(pop: dict, days: Sequence[dict]) -> List[str]:
    out: List[str] = []
    identified = pop["run_verdicts"].get(RUN_IDENTIFIED, 0)
    if not identified:
        out.append("[НЕ ИЗМЕРЕНО] ни один день журнала не опознан по прогону — "
                   "носитель прогонов не покрывает окно журнала")
        return out

    last = pop["positions"].get(POS_LAST, 0)
    only = pop["positions"].get(POS_ONLY, 0)
    earlier = pop["orientations"].get(ORIENT_RECORD_EARLIER, 0)

    out.append(
        f"[ОТВЕТ] запись видит ОДИН снимок — снимок СВОЕГО прогона, а не выбор "
        f"из дневного набора: из {identified} опознанных дней выживший прогон "
        f"оказался последним в дне {last + only} раз "
        f"(из них {only} дней имели ровно один прогон)")

    if pop["days_with_replacement"]:
        out.append(
            f"[ОТВЕТ] выбора нет — есть гонка: на {pop['days_with_replacement']} "
            f"днях прогонов было больше одного, и строку дня переписывал каждый "
            f"следующий; в журнал не попало {pop['runs_not_in_journal']} прогонов")

    if earlier == identified:
        out.append(
            f"[CRITICAL] отметка записи есть отметка НАЧАЛА её собственного "
            f"прогона: на {earlier} опознанных днях из {identified} (100 %) "
            f"cycle_start позже generated_at записи. Значит ЛЮБОЙ артефакт того "
            f"же прогона — снимок оркестратора, предложение аллокатора, вердикт "
            f"риска — по построению новее записи, и порядок отметок не может "
            f"свидетельствовать о том, читала запись этот артефакт или нет")
    elif earlier:
        out.append(
            f"[ИНФО] отметка записи предшествует старту своего прогона на "
            f"{earlier} днях из {identified} — порядок отметок ненадёжен как "
            f"свидетельство чтения")

    single = pop["snapshot_verdicts"].get(SNAP_SINGLE, 0)
    mixed = pop["snapshot_verdicts"].get(SNAP_MIXED, 0)
    if mixed:
        out.append(
            f"[CRITICAL] на {mixed} днях ноги записи опознают РАЗНЫЕ снимки — "
            f"запись склеена из нескольких моментов, и «один снимок на запись» "
            f"для этих дней неверно")
    if single:
        pointed_last = sum(1 for e in days
                           if e["snapshot"].get("verdict") == SNAP_SINGLE
                           and e["snapshot"].get("snapshot_is_last_known"))
        out.append(
            f"[ОТВЕТ] опознание снимка ПО ЗНАЧЕНИЮ (не по времени): {single} "
            f"дней опознаны однозначно, из них {pointed_last} указывают на "
            f"последний известный носителю снимок дня")

    measured_live = [e["live_snapshot"] for e in days if "live_snapshot" in e]
    for live in measured_live:
        if live["legs_equal"] and live["snapshot_newer_than_record"]:
            out.append(
                f"[CRITICAL] прямой контроль на ловушку: живой снимок новее "
                f"записи на {live['snapshot_minus_record_s']} с — и при этом "
                f"{live['legs_equal']} из {live['legs_equal'] + live['legs_differ']} "
                f"сравнимых ног совпадают ТОЧНО. Правило «снимок новее записи ⇒ "
                f"запись не могла его видеть» отвергает здесь снимок, который "
                f"запись доказуемо прочитала")

    if pop["hidden_distinct_live_targets"]:
        out.append(
            f"[ИНФО] нижняя граница движения входов в затёртых днях: живой "
            f"аллокатор произвёл за эти дни на "
            f"{pop['hidden_distinct_live_targets']} РАЗНЫХ целей больше, чем "
            f"дней; величина чужая (не теневая) и служит только границей снизу")

    for name, key in ((RUN_NO_START, "прогон не опознан окном"),
                      (RUN_AMBIGUOUS, "кандидатов на прогон больше одного"),
                      (RUN_NO_CARRIER, "носителя прогонов за день нет")):
        n = pop["run_verdicts"].get(name, 0)
        if n:
            out.append(f"[НЕ ИЗМЕРЕНО] {key}: {n} дн.")
    n = pop["snapshot_verdicts"].get(SNAP_NO_MATCH, 0)
    if n:
        out.append(
            f"[НЕ ИЗМЕРЕНО] снимок не опознан ни одной ногой: {n} дн. — рода "
            f"величин у носителя (hint_winner) и у записи (ставка протокола) "
            f"РАЗНЫЕ, и несовпадение дырой транскрипции не объявляется")
    return out


def _status(pop: dict, findings: Sequence[str]) -> str:
    if any(f.startswith("[CRITICAL]") for f in findings):
        return STATUS_CRITICAL
    if not pop["run_verdicts"].get(RUN_IDENTIFIED, 0):
        return STATUS_UNMEASURED
    if any(f.startswith("[ИНФО]") for f in findings):
        return STATUS_WARNING
    return STATUS_OK


def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: население → опознание → ответы → отказы."""
    out: List[str] = []
    pop = doc.get("population") or {}
    out.append(
        f"   сколько снимков видит запись (заказ #550/#551): {doc.get('status')} · "
        f"дней журнала {doc.get('journal_rows')} · опознано по прогону "
        f"{(pop.get('run_verdicts') or {}).get(RUN_IDENTIFIED, 0)} · дней с "
        f"заменой {pop.get('days_with_replacement')} · прогонов вне журнала "
        f"{pop.get('runs_not_in_journal')}")
    positions = pop.get("positions")
    if positions:
        out.append("   положение выжившего прогона: "
                   + " · ".join(f"{k}={v}" for k, v in sorted(positions.items())))
    orientations = pop.get("orientations")
    if orientations:
        out.append("   отметка записи против старта своего прогона: "
                   + " · ".join(f"{k}={v}" for k, v in sorted(orientations.items())))
    for line in doc.get("findings") or []:
        out.append(f"   {line}")
    if doc.get("does_not_report"):
        out.append(f"   НЕ ДОКЛАДЫВАЕТ: {doc['does_not_report']}")
    if doc.get("advisory"):
        out.append(f"   ADVISORY: {doc['advisory']}")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, **kwargs) -> dict:
    """Форма, которую ждут ступень переписей `findings_bridge` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = measure(data_dir, now=now, **kwargs)
    findings = list(doc.get("findings") or [])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for x in findings if x.startswith("[CRITICAL]")),
        "warn": sum(1 for x in findings if x.startswith("[ИНФО]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ]")),
        # «не измерено» считается ОТДЕЛЬНО от нулей: растворив его, мы сделали бы
        # молчание прибора неотличимым от чистого прогона.
        "unchecked": (1 if doc["status"] == STATUS_UNMEASURED else 0)
                     + sum(1 for x in findings if x.startswith("[НЕ ИЗМЕРЕНО]")),
    }
    if write:
        atomic_save(doc, str(data_dir / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="сколько снимков в день видит запись решения и один ли это "
                    "выбор (заказ #550/#551)")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    data_dir = (Path(args.data_dir) if args.data_dir
                else Path(os.environ.get("SPA_DATA_DIR")
                          or (Path(__file__).resolve().parents[2] / "data")))
    doc = measure(data_dir)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(data_dir) / OUTPUT_FILENAME))
    for line in format_report(doc):
        print(line)
    return 0 if doc["status"] in (STATUS_OK, STATUS_WARNING) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
