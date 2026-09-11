"""Сколько наблюдений ставки доказуемы НЕ из носителя (заказ #557, ADR-320).

Заказ цикла #557 поставлен дословно так:

> **Что именно стои́т между НАБЛЮДЕНИЕМ ставки и её ЗАПИСЬЮ на днях знаменателя —
> и сколько наблюдений теряется там, где носитель сделал одно?**
> … Первым результатом обязано быть **число наблюдений, доказуемых НЕ из этого
> носителя** (журнал расхождений фидов, ``adapter_status``, git-история
> ``POLLED_ADAPTERS`` по дню — те же носители, которыми ADR-311 доказал 28 из 31)
> на тех же 2 днях знаменателя. Ноль доказуемых ⇒ **третий исход**: «носитель не
> терял, наблюдение и было одно», и тогда ветка закрыта не записью, а опросом.
> И отдельно: число наблюдений НЕ есть число пригодных к сравнению — сказать это
> надо прежде, чем называть разницу.

Прибор исполняет этот порядок буквально, и его слои отвечают на РАЗНЫЕ вопросы.

## Слой 0 — НЕЗАВИСИМОСТЬ источника. Меряется, а не принимается на веру

Заказ назвал три кандидата в независимые свидетели. Прежде чем считать ими
что-либо, прибор проверяет, независимы ли они от носителя ВООБЩЕ, — потому что
«второй свидетель» и «тот же свидетель, записанный дважды» дают одно и то же
число и разную правду.

Признак независимости здесь структурный и проверяемый: у двух носителей должны
быть РАЗНЫЕ производители. Прибор сверяет множество меток прогона у носителя с
множеством меток у кандидата на общих днях: совпало ПОЛНОСТЬЮ на всех общих днях
⇒ кандидат помечается ``same_producer_suspect`` и его вклад в «доказуемо НЕ из
носителя» равен нулю по построению. Это не приговор кандидату, а отказ считать
его показание вторым.

## Слой 1 — ОСЬ ПРОГОНОВ. Первый результат, как велел заказ

Вопрос слоя: **сколько прогонов дня доказуемы носителем, который носителю ставок
не родня.** Единица счёта — прогон (метка ``run_ts``), а не строка и не значение.

Знаменатель — ``scored``-дни у КАНОНИЧЕСКОГО производителя
(``shadow_trigger_eval``), а не выписанный сюда список: ровно тот же источник, что
у ADR-318, иначе два прибора спорили бы о населении, а не о предмете.

**Окно кандидата — часть ответа, а не сноска.** ``orchestrator_runs.json`` есть
кольцевой буфер на ``max_runs`` прогонов: день СТАРШЕ самого раннего прогона в
буфере неизмерим ПО ПОСТРОЕНИЮ. Такой день получает ``UNMEASURED_WINDOW``, и ноль
прогонов ему не приписывается никогда — «не измерено», выданное за «наблюдений не
было», и есть тот дефект, ради которого заказ потребовал третий исход.

## Слой 2 — ПРИГОДНОСТЬ К СРАВНЕНИЮ. Сказано ПРЕЖДЕ, чем названа разница

Заказ назвал ловушку заранее, и она разводит два числа, которые кажутся одним:

* **наблюдение** — прогон состоялся и ставка кем-то наблюдена;
* **пригодное к сравнению** — про ЭТУ ногу есть ДВА значения в РАЗНЫХ прогонах
  одного дня.

``orchestrator_runs.json`` несёт на прогон ставку РОВНО ОДНОГО протокола (``summary.
best_apy`` — победителя прогона). Значит десять прогонов дня дают десять
наблюдений и при этом могут не дать НИ ОДНОЙ пригодной пары для ноги, которая ни
разу не была победителем. Классы нерассуженной пары названы порознь, потому что
чинится у них разное: ``leg_never_winner`` — составом того, что носитель пишет на
прогон; ``one_observation`` — частотой опроса; ``day_outside_window`` — глубиной
кольцевого буфера.

Разница ставок печатается ТОЛЬКО для пригодных пар и ТОЛЬКО после того, как
напечатано, сколько пар пригодно.

**Сравнение размаха с маржой цели прибор НЕ производит**, когда маржи для ключа
нет в ``target_stability.json``: «размах больше маржи» без маржи есть выдуманное
число, а не вывод. Отсутствие маржи печатается ключом, а не умалчивается.

## Слой 3 — МЕХАНИЗМ. Что именно стои́т между наблюдением и записью

Носитель ставок пишется НЕ оркестратором. Его пишет пробег офиса
(``findings_bridge`` → ``apy_composition.run`` → ``append_history``), у которого
свои часы: он просыпается и переписывает ТОТ снимок, который в этот момент лежит
на диске. Снимок оркестратора — СЛОТ, а не журнал: прогон N+1 затирает прогон N.
Поэтому между наблюдением и записью стоит не сбой и не фид, а **переписчик с
более грубым тактом**, и всё, что прошло между двумя его пробуждениями, исчезает
до переписи.

Слой меряет это, а не рассказывает: для каждого дня сопоставляются пробуждения
переписчика (``observed_at`` носителя), переписанные им снимки (``snapshot``) и
прогоны независимого носителя. Прогон, не ставший ничьим ``snapshot``, получает
класс ``overwritten_before_transcription``.

## Слой 4 — КОНТРОЛЬ НА НЕСВЯЗАННОМ НАСЕЛЕНИИ, и он печатается ПОСЛЕ

Дни, которых носитель касается, могут в знаменатель не входить. Потери на них
реальны и к знаменателю отношения не имеют; доля с одного населения на другое не
переносится (та же дисциплина, что в ADR-318). Слой печатается последним
намеренно.

## ADVISORY

Прибор ничего не чинит и не предлагает чинить молча. Ни писатель журнала решений и
его правило замены строки дня, ни писатель носителя, ни такт переписчика, ни
``max_runs`` кольцевого буфера, ни ``POLLED_ADAPTERS``, ни пины, ни ``MIN_HIT_RATE``,
ни ``TriggerParams``, ни пороги RiskPolicy v1.0, ни потолки концентрации, ни
стоп-кран, ни живой трек не трогаются; капитал не двигается. Живое ``data/``
открывается на запись ровно один раз — для собственного артефакта.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

VERSION = "rate_observation_census/v1"

OUTPUT_FILENAME = "rate_observation_census.json"

#: Носитель ПОД ИСПЫТАНИЕМ — тот, о котором заказ спрашивает «сколько он потерял».
CARRIER_FILENAME = "apy_composition_log.jsonl"
#: Кандидат в НЕЗАВИСИМЫЕ свидетели: пишется самим оркестратором (`_append_run`),
#: строка на ПРОГОН. Заказом не назван — найден замером населения носителей.
RUNS_FILENAME = "orchestrator_runs.json"
#: Кандидат, НАЗВАННЫЙ заказом. Его независимость — предмет слоя 0, а не посылка.
DIVERGENCE_FILENAME = "adapter_feed_divergence_log.jsonl"
#: Журнал решений: из него берутся ноги дня (население пар), ровно как в ADR-318.
JOURNAL_FILENAME = "allocation_rationale_history.jsonl"
#: Маржи цели. Нет маржи для ключа ⇒ размах с ней НЕ сравнивается.
STABILITY_FILENAME = "target_stability.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Разряд сравнения ставок: носитель и журнал пишут проценты с четырьмя знаками.
_PP = 4

#: Классы дня на оси прогонов.
DAY_UNMEASURED_WINDOW = "outside_independent_window"
DAY_MEASURED = "measured"
#: ГРАНИЧНЫЙ день насыщенного кольцевого буфера. День СТАРШЕ границы буфер уже не
#: помнит, и про него честно говорится «не измерено». А сам граничный день буфер
#: помнит ЧАСТИЧНО: вытеснение идёт с головы (`runs[-max_runs:]`), поэтому его
#: прогоны срезаны ровно настолько, насколько буфер успел переполниться. Число на
#: таком дне есть НИЖНЯЯ ГРАНИЦА, а не счёт, и выдавать его за счёт — тот самый
#: дефект «не измерено, выданное за ответ», ради которого заказ требовал третий
#: исход. Замер #562: автор #561 намерил на 2026-09-02 десять прогонов, я на том
#: же неизменном коде — девять; вердикт сдвинул не код, а вытеснение.
DAY_BOUNDARY_TRUNCATED = "boundary_truncated"

#: Классы пары «день × нога» на оси пригодности к сравнению.
PAIR_JUDGED = "judged"
PAIR_LEG_NEVER_WINNER = "leg_never_winner"
PAIR_ONE_OBSERVATION = "one_observation"
PAIR_DAY_OUTSIDE_WINDOW = "day_outside_window"
#: То же вытеснение на оси пригодности, и здесь у путаницы есть ЦЕНА. Классы
#: названы порознь потому, что чинятся разным рычагом: `one_observation` — частотой
#: опроса, `day_outside_window` — глубиной буфера. На граничном дне «наблюдение
#: одно» и «второе вытеснено» неразличимы, и записать там `one_observation` значит
#: послать ремонт не к тому рычагу.
PAIR_DAY_BOUNDARY_TRUNCATED = "day_boundary_truncated"

#: Классы прогона на оси механизма.
RUN_TRANSCRIBED = "transcribed"
RUN_OVERWRITTEN = "overwritten_before_transcription"


# ─── чтение ────────────────────────────────────────────────────────────────────

def _read_jsonl(path: Path) -> Tuple[List[dict], str]:
    """Строки JSONL. Любой отказ — с НАЗВАННОЙ причиной, не пустым списком."""
    if not path.exists():
        return [], f"файла нет: {path.name}"
    rows: List[dict] = []
    broken = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    broken += 1
                    continue
                if isinstance(rec, dict):
                    rows.append(rec)
    except OSError as exc:
        return [], f"{path.name} не прочитан: {exc}"
    if broken:
        return rows, f"{path.name}: строк не разобрано {broken}"
    return rows, ""


def _read_json(path: Path) -> Tuple[Optional[object], str]:
    if not path.exists():
        return None, f"файла нет: {path.name}"
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), ""
    except (OSError, ValueError) as exc:
        return None, f"{path.name} не прочитан: {exc}"


def scored_days(data_dir: Path) -> Optional[Set[str]]:
    """Дни знаменателя ``hit_rate`` — у КАНОНИЧЕСКОГО производителя.

    Тот же источник, что у ADR-318 (``shadow_trigger_eval``). Не ответил ⇒
    ``None``, то есть «не измерено», а не пустое множество: пустое читалось бы
    как «знаменатель пуст», и прибор объявил бы полное покрытие нуля.
    """
    try:
        from spa_core.paper_trading import shadow_trigger_eval as ste
        report = ste.evaluate_window(Path(data_dir), write=False)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("знаменатель hit_rate не измерен: %s", exc)
        return None
    rows = report.get("per_verdict")
    if not isinstance(rows, list):
        return None
    return {str(r.get("cycle_date")) for r in rows
            if not r.get("trivial") and r.get("outcome") in ("hit", "miss")}


# ─── разбор носителей ──────────────────────────────────────────────────────────

def carrier_snapshots(rows: List[dict]) -> Dict[str, Set[str]]:
    """День → множество меток ``snapshot`` носителя под испытанием."""
    out: Dict[str, Set[str]] = {}
    for rec in rows:
        snap = rec.get("snapshot")
        if isinstance(snap, str) and len(snap) >= 10:
            out.setdefault(snap[:10], set()).add(snap)
    return out


def carrier_wakeups(rows: List[dict]) -> Dict[str, Dict[str, str]]:
    """День → {метка снимка: когда переписчик её записал (``observed_at``)}.

    Именно ЭТА пара и есть предмет заказа: ``snapshot`` — когда значение
    наблюдено, ``observed_at`` — когда оно переписано (ADR-320 показал, что оси
    расходятся на часы, и выбор поля решает всё).
    """
    out: Dict[str, Dict[str, str]] = {}
    for rec in rows:
        snap, seen = rec.get("snapshot"), rec.get("observed_at")
        if isinstance(snap, str) and len(snap) >= 10 and isinstance(seen, str):
            out.setdefault(snap[:10], {}).setdefault(snap, seen)
    return out


def independent_runs(doc: object) -> Tuple[Dict[str, Dict[str, Optional[Tuple[str, float]]]],
                                           Optional[str], str]:
    """День → {метка прогона: (протокол-победитель, его ставка) | None}.

    Второй результат — САМЫЙ РАННИЙ прогон буфера. Он и есть граница окна: день
    старше него неизмерим по построению, и прибор обязан это сказать, а не
    показать ноль.
    """
    if not isinstance(doc, dict):
        return {}, None, "orchestrator_runs.json: не объект"
    runs = doc.get("runs")
    if not isinstance(runs, list):
        return {}, None, "orchestrator_runs.json: нет списка runs"
    out: Dict[str, Dict[str, Optional[Tuple[str, float]]]] = {}
    earliest: Optional[str] = None
    for rec in runs:
        if not isinstance(rec, dict):
            continue
        ts = rec.get("run_ts")
        if not isinstance(ts, str) or len(ts) < 10:
            continue
        if earliest is None or ts < earliest:
            earliest = ts
        best = ((rec.get("summary") or {}) if isinstance(rec.get("summary"), dict)
                else {}).get("best_apy")
        pair: Optional[Tuple[str, float]] = None
        if isinstance(best, dict):
            proto, apy = best.get("protocol"), best.get("apy_pct")
            if isinstance(proto, str) and isinstance(apy, (int, float)):
                pair = (proto, round(float(apy), _PP))
        out.setdefault(ts[:10], {})[ts] = pair
    return out, earliest, ""


def buffer_saturated(doc: object) -> Optional[bool]:
    """Переполнен ли кольцевой буфер прогонов — `True` / `False` / `None`.

    Вопрос отдельный от «какой день самый ранний», и задаётся он отдельно нарочно.
    Пока буфер НЕ полон, вытеснения не было вовсе и самый ранний день измерен
    целиком; как только `len(runs) >= max_runs`, голова срезана и граничный день
    неполон ПО ПОСТРОЕНИЮ. Один и тот же день, таким образом, честен или срезан в
    зависимости от наполнения — и спрашивать надо наполнение, а не дату.

    `None` — «не измерено»: документ не прочитан или `max_runs` не назван. Это
    третий исход, а не `False`: `False` означал бы «вытеснения точно не было», то
    есть утверждение, которого никто не делал.
    """
    if not isinstance(doc, dict):
        return None
    runs = doc.get("runs")
    if not isinstance(runs, list):
        return None
    max_runs = doc.get("max_runs")
    if not isinstance(max_runs, int) or isinstance(max_runs, bool) or max_runs <= 0:
        return None
    return len(runs) >= max_runs


def divergence_keys(rows: List[dict]) -> Tuple[Dict[str, Set[str]],
                                               Dict[str, Set[Tuple[str, str]]]]:
    """День → метки стороны носителя и ПАРЫ «сторона носителя ↔ прогон».

    ``snapshot_key`` записан как «сторона A|сторона оркестратора». Пары хранятся
    ПОИМЁННО, а не двумя независимыми множествами: множества ответили бы «на этом
    дне какая-то левая сторона переписана и какие-то прогоны есть», а вопрос —
    «переписан ли ИМЕННО ЭТОТ прогон».
    """
    side_a: Dict[str, Set[str]] = {}
    pairs: Dict[str, Set[Tuple[str, str]]] = {}
    for rec in rows:
        key = rec.get("snapshot_key")
        if not isinstance(key, str) or "|" not in key:
            continue
        left, right = key.split("|", 1)
        if len(left) >= 10:
            side_a.setdefault(left[:10], set()).add(left)
        if len(left) >= 10 and len(right) >= 10:
            pairs.setdefault(right[:10], set()).add((left, right))
    return side_a, pairs


def journal_legs(rows: List[dict]) -> Dict[str, List[str]]:
    """День → ноги дня (``current_positions ∪ target_positions``), как в ADR-318."""
    out: Dict[str, List[str]] = {}
    for rec in rows:
        day = rec.get("cycle_date")
        if not isinstance(day, str):
            continue
        names: Set[str] = set()
        for book in (rec.get("current_positions"), rec.get("target_positions")):
            if isinstance(book, dict):
                names.update(str(k) for k in book)
        out[str(day)] = sorted(names)
    return out


def stability_margins(doc: object) -> Dict[str, float]:
    """Ключ → маржа цели. Нет ключа — нет и сравнения; выдумывать нечего."""
    out: Dict[str, float] = {}
    if not isinstance(doc, dict):
        return out
    protos = doc.get("protocols")
    if not isinstance(protos, list):
        return out
    for rec in protos:
        if not isinstance(rec, dict):
            continue
        key = rec.get("protocol") or rec.get("key")
        margin = rec.get("margin_pp")
        if isinstance(key, str) and isinstance(margin, (int, float)):
            out[key] = round(float(margin), _PP)
    return out


# ─── слой 0: независимость кандидата ───────────────────────────────────────────

def independence_probe(carrier: Dict[str, Set[str]],
                       candidate: Dict[str, Set[str]],
                       name: str) -> dict:
    """Совпали ли метки кандидата с метками носителя на ВСЕХ общих днях.

    Совпали полностью ⇒ у них один производитель, и показание кандидата не
    второе, а то же самое. Это структурный признак, а не догадка: два разных
    писателя не могут из цикла в цикл выдавать один и тот же набор меток с
    точностью до микросекунды.
    """
    shared = sorted(set(carrier) & set(candidate))
    if not shared:
        return {"candidate": name, "verdict": "unmeasured",
                "shared_days": 0, "identical_days": 0,
                "reason": "общих дней с носителем нет — независимость не измерена"}
    identical = [d for d in shared if carrier[d] == candidate[d]]
    same = len(identical) == len(shared)
    return {
        "candidate": name,
        "verdict": "same_producer_suspect" if same else "independent",
        "shared_days": len(shared),
        "identical_days": len(identical),
        "reason": (
            f"метки совпали на {len(identical)} из {len(shared)} общих дней — "
            "показание не второе, а то же самое" if same else
            f"метки разошлись на {len(shared) - len(identical)} из "
            f"{len(shared)} общих дней — производители разные"),
    }


# ─── слой 1: ось прогонов ──────────────────────────────────────────────────────

def run_axis(days: List[str],
             carrier: Dict[str, Set[str]],
             runs: Dict[str, Dict[str, Optional[Tuple[str, float]]]],
             earliest_run: Optional[str],
             saturated: Optional[bool] = None) -> List[dict]:
    """По дню знаменателя: прогонов доказуемо · переписано носителем · потеряно.

    `saturated` — ответ `buffer_saturated`. При `True` граничный день буфера
    получает класс `DAY_BOUNDARY_TRUNCATED`, и его число объявляется НИЖНЕЙ
    ГРАНИЦЕЙ: вытеснение идёт с головы, значит на этом дне буфер помнит «не менее
    чем», а сколько было на самом деле — не помнит никто. При `False` (буфер не
    полон) вытеснения не было и граничный день измерен целиком — обратная сторона
    обязана работать, иначе проверка метила бы срезанным ЛЮБОЙ ранний день.
    `None` (не измерено) ведёт себя как `False`: приписывать срез, не померив
    наполнения, значило бы выдумать его.
    """
    out: List[dict] = []
    boundary = (earliest_run or "")[:10]
    for day in days:
        snaps = carrier.get(day, set())
        if earliest_run is not None and day < boundary:
            out.append({
                "day": day, "klass": DAY_UNMEASURED_WINDOW,
                "runs_provable": None, "carrier_snapshots": len(snaps),
                "observations_outside_carrier": None,
                "reason": (
                    f"день старше самого раннего прогона буфера ({boundary}) — "
                    "кольцевой буфер его уже не помнит; ноль сюда не пишется"),
            })
            continue
        day_runs = runs.get(day, {})
        truncated = bool(saturated) and earliest_run is not None and day == boundary
        out.append({
            "day": day,
            "klass": DAY_BOUNDARY_TRUNCATED if truncated else DAY_MEASURED,
            "runs_provable": len(day_runs),
            "runs_provable_is_floor": truncated,
            "carrier_snapshots": len(snaps),
            "observations_outside_carrier": max(0, len(day_runs) - len(snaps)),
            "reason": (
                f"граничный день буфера ({boundary}), и буфер ПОЛОН: вытеснение "
                f"идёт с головы, поэтому {len(day_runs)} — нижняя граница числа "
                "прогонов дня, а не их счёт. Наблюдения, попавшие в это число, "
                "доказаны; отсутствие остальных — нет"
            ) if truncated else None,
        })
    return out


# ─── слой 2: пригодность к сравнению ───────────────────────────────────────────

def comparable_axis(days: List[str],
                    legs: Dict[str, List[str]],
                    runs: Dict[str, Dict[str, Optional[Tuple[str, float]]]],
                    margins: Dict[str, float],
                    earliest_run: Optional[str],
                    saturated: Optional[bool] = None) -> List[dict]:
    """По паре «день знаменателя × нога»: пригодна ли она к сравнению, и почему нет.

    Пригодна тогда и только тогда, когда независимый носитель дал ноге ДВА и
    более значения в РАЗНЫХ прогонах этого дня. Одно значение не сравнивается ни
    с чем, а «значений два и они равны» — совсем другой ответ, чем «значение одно».
    """
    boundary = (earliest_run or "")[:10]
    out: List[dict] = []
    for day in days:
        outside = earliest_run is not None and day < boundary
        truncated = bool(saturated) and earliest_run is not None and day == boundary
        by_leg: Dict[str, List[Tuple[str, float]]] = {}
        for ts, pair in sorted(runs.get(day, {}).items()):
            if pair is not None:
                by_leg.setdefault(pair[0], []).append((ts, pair[1]))
        for leg in legs.get(day, []):
            obs = by_leg.get(leg, [])
            if outside:
                klass, rng = PAIR_DAY_OUTSIDE_WINDOW, None
            elif len(obs) >= 2:
                # Вытеснение умеет только УБИРАТЬ наблюдения, не добавлять:
                # два уцелевших значения остаются двумя и на срезанном дне,
                # поэтому пара судится как обычно.
                klass = PAIR_JUDGED
                values = [v for _, v in obs]
                rng = round(max(values) - min(values), _PP)
            elif truncated:
                # А вот «меньше двух» на граничном дне полного буфера НЕ значит
                # «больше не наблюдали»: недостающее могло быть вытеснено. Два
                # класса ниже чинятся разными рычагами (частота опроса против
                # глубины буфера), и выбрать между ними здесь нечем.
                klass, rng = PAIR_DAY_BOUNDARY_TRUNCATED, None
            elif len(obs) == 1:
                klass, rng = PAIR_ONE_OBSERVATION, None
            else:
                klass, rng = PAIR_LEG_NEVER_WINNER, None
            row = {
                "day": day, "leg": leg, "klass": klass,
                "observations": len(obs) if not outside else None,
                "distinct_values": (len({v for _, v in obs})
                                    if obs and not outside else None),
                "range_pp": rng,
                "margin_pp": margins.get(leg),
            }
            if klass == PAIR_JUDGED and leg not in margins:
                row["margin_comparison"] = (
                    "НЕ ИЗМЕРЕНО: маржи цели для этого ключа нет в "
                    "target_stability.json — размах с ней не сравнивается")
            elif klass == PAIR_JUDGED:
                row["margin_comparison"] = (
                    "exceeds_margin" if rng is not None and rng > margins[leg]
                    else "within_margin")
            out.append(row)
    return out


# ─── слой 3: механизм ──────────────────────────────────────────────────────────

def mechanism_axis(days: List[str],
                   wakeups: Dict[str, Dict[str, str]],
                   runs: Dict[str, Dict[str, Optional[Tuple[str, float]]]],
                   pairs: Dict[str, Set[Tuple[str, str]]]) -> List[dict]:
    """Что стои́т между наблюдением и записью — по дням, где носитель работал.

    Прогон считается переписанным, если он стои́т ПРАВОЙ стороной пары, чья ЛЕВАЯ
    сторона есть среди снимков, которые переписчик записал. Пары нет ⇒ прогон
    никем не переписан: он был затёрт на диске следующим прогоном до того, как
    переписчик проснулся.

    Проверять надо именно пару. «На дне есть переписанная левая сторона И есть
    правые стороны» — верный ответ не на тот вопрос: он объявил бы переписанными
    все прогоны дня, стоило переписаться одному.
    """
    out: List[dict] = []
    for day in days:
        day_wake = wakeups.get(day, {})
        if not day_wake:
            continue
        transcribed_a = set(day_wake)
        paired = {right for left, right in pairs.get(day, set())
                  if left in transcribed_a}
        day_runs = sorted(runs.get(day, {}))
        klass_by_run = {
            ts: (RUN_TRANSCRIBED if ts in paired else RUN_OVERWRITTEN)
            for ts in day_runs
        }
        out.append({
            "day": day,
            "transcriber_wakeups": sorted(day_wake.values()),
            "snapshots_transcribed": sorted(transcribed_a),
            "runs": len(day_runs),
            "transcribed": sum(1 for k in klass_by_run.values()
                               if k == RUN_TRANSCRIBED),
            "overwritten_before_transcription": sorted(
                ts for ts, k in klass_by_run.items() if k == RUN_OVERWRITTEN),
        })
    return out


# ─── сборка ────────────────────────────────────────────────────────────────────

def _findings(doc: dict) -> List[str]:
    out: List[str] = []
    ind = doc["independence"]
    for probe in ind:
        if probe["verdict"] == "same_producer_suspect":
            out.append(
                f"[СЛОЙ 0] кандидат `{probe['candidate']}` НЕ независим от "
                f"носителя: {probe['reason']}. Его показание в счёт «доказуемо НЕ "
                "из носителя» не идёт")
    axis = doc["run_axis"]
    measured = [r for r in axis if r["klass"] == DAY_MEASURED]
    boundary_rows = [r for r in axis if r["klass"] == DAY_BOUNDARY_TRUNCATED]
    countable = measured + boundary_rows
    unmeasured = [r for r in axis if r["klass"] == DAY_UNMEASURED_WINDOW]
    touched = [r for r in countable if r["carrier_snapshots"] > 0]
    untouched = [r for r in countable if r["carrier_snapshots"] == 0]
    if touched:
        lost = sum(r["observations_outside_carrier"] for r in touched)
        names = ", ".join(r["day"] for r in touched)
        if lost == 0:
            out.append(
                f"[ОТВЕТ ЗАКАЗУ, третий исход] на {len(touched)} дн. знаменателя, "
                f"которых носитель КАСАЕТСЯ ({names}), наблюдений, доказуемых не "
                "из него, — НОЛЬ: независимый носитель даёт ровно столько же "
                "прогонов, сколько носитель переписал. Носитель не терял, "
                "наблюдение и было одно; ветка закрыта не записью, а ОПРОСОМ")
        else:
            out.append(
                f"[ОТВЕТ ЗАКАЗУ] на {len(touched)} дн. знаменателя, которых "
                f"носитель касается ({names}), независимый носитель доказывает "
                f"{lost} наблюдени(е/я/й) сверх переписанных носителем")
    if untouched:
        extra = sum(r["runs_provable"] for r in untouched)
        worst = max(untouched, key=lambda r: r["runs_provable"])
        if extra:
            out.append(
                f"[CRITICAL] ветка мерила ОДИН носитель: ещё на {len(untouched)} "
                f"дн. знаменателя, которых он не касается вовсе, независимый "
                f"носитель доказывает {extra} прогон(а/ов) — до "
                f"{worst['runs_provable']} за день ({worst['day']}). «Носитель "
                "рассуживает 0 пар из 75» было утверждением о НОСИТЕЛЕ, а "
                "прочитано как утверждение о знаменателе")
    if boundary_rows:
        names = ", ".join(r["day"] for r in boundary_rows)
        floor = sum(r["observations_outside_carrier"] or 0 for r in boundary_rows)
        out.append(
            f"[НИЖНЯЯ ГРАНИЦА] {len(boundary_rows)} дн. ({names}) — граничные для "
            "ПОЛНОГО кольцевого буфера: вытеснение идёт с головы, поэтому число "
            f"их прогонов срезано, и {floor} наблюдени(е/я/й) отсюда суть «не "
            "менее чем». Доказанное доказано; «больше не было» отсюда НЕ следует, "
            "и общий счёт наблюдений вне носителя есть нижняя граница. Замер "
            "#562: на том же неизменном коде граничный день дал 10 прогонов "
            "утром и 9 через час — сдвинул вердикт не код, а вытеснение")
    pair_trunc = [x for x in doc["comparable_axis"]
                  if x["klass"] == PAIR_DAY_BOUNDARY_TRUNCATED]
    if pair_trunc:
        out.append(
            f"[НИЖНЯЯ ГРАНИЦА] {len(pair_trunc)} пар(ы) «день × нога» на "
            "граничном дне не отнесены ни к `one_observation`, ни к "
            "`leg_never_winner`: на срезанном дне эти два класса неразличимы, а "
            "чинятся они РАЗНЫМ рычагом — частотой опроса против глубины буфера. "
            "Выбор между ними здесь был бы догадкой, посланной ремонту как факт")
    if unmeasured:
        out.append(
            f"[НЕ ИЗМЕРЕНО] {len(unmeasured)} дн. знаменателя старше окна "
            "кольцевого буфера независимого носителя — ноль прогонов им не "
            "приписан: «не измерено», выданное за «наблюдений не было», и есть "
            "тот дефект, против которого заказ потребовал третий исход")
    pairs = doc["comparable_axis"]
    judged = [p for p in pairs if p["klass"] == PAIR_JUDGED]
    never = sum(1 for p in pairs if p["klass"] == PAIR_LEG_NEVER_WINNER)
    out.append(
        f"[ПРИГОДНОСТЬ ≠ НАБЛЮДЕНИЕ] пар «день знаменателя × нога» {len(pairs)}; "
        f"пригодны к сравнению {len(judged)}; не пригодны, потому что нога ни "
        f"разу не была победителем прогона, — {never}. Независимый носитель несёт "
        "на прогон ставку РОВНО ОДНОГО протокола, поэтому десять наблюдений дня "
        "и ноль пригодных пар — совместимые числа")
    for p in judged:
        tail = p.get("margin_comparison") or ""
        out.append(
            f"[ДВИЖЕНИЕ] {p['day']} · {p['leg']}: наблюдений {p['observations']}, "
            f"различных значений {p['distinct_values']}, размах "
            f"{p['range_pp']} пп — {tail}")
    mech = doc["mechanism"]
    over = sum(len(m["overwritten_before_transcription"]) for m in mech)
    if mech:
        runs_total = sum(m["runs"] for m in mech)
        out.append(
            f"[МЕХАНИЗМ] между наблюдением и записью стои́т ПЕРЕПИСЧИК со своим "
            f"тактом: носитель пишется пробегом офиса, который переписывает тот "
            f"снимок, что лежит на диске в минуту его пробуждения. На днях работы "
            f"носителя прогонов {runs_total}, переписано {runs_total - over}, "
            f"затёрто следующим прогоном до переписи {over}. Снимок оркестратора "
            "есть СЛОТ, а не журнал")
    # Слой 4 печатается ПОСЛЕДНИМ намеренно: читатель, увидевший первой строкой
    # «переписчик теряет прогоны», прочтёт это как замер знаменателя.
    outside = doc["outside_denominator"]
    if outside:
        o_runs = sum(m["runs"] for m in outside)
        o_lost = sum(len(m["overwritten_before_transcription"]) for m in outside)
        worst = max(outside,
                    key=lambda m: len(m["overwritten_before_transcription"]))
        out.append(
            f"[КОНТРОЛЬ, НЕСВЯЗАННОЕ НАСЕЛЕНИЕ] на {len(outside)} дн., которых "
            f"носитель касается, а знаменатель НЕ содержит: прогонов {o_runs}, "
            f"затёрто до переписи {o_lost} (худший день {worst['day']} — "
            f"{len(worst['overwritten_before_transcription'])}). Потеря реальна и "
            "к знаменателю отношения не имеет: доля отсюда туда не переносится")
    return out


def build(data_dir: Path, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    data_dir = Path(data_dir)

    carrier_rows, carrier_why = _read_jsonl(data_dir / CARRIER_FILENAME)
    runs_doc, runs_why = _read_json(data_dir / RUNS_FILENAME)
    div_rows, div_why = _read_jsonl(data_dir / DIVERGENCE_FILENAME)
    journal_rows, journal_why = _read_jsonl(data_dir / JOURNAL_FILENAME)
    stability_doc, _ = _read_json(data_dir / STABILITY_FILENAME)

    doc: dict = {
        "schema": VERSION,
        "generated_at": now.isoformat(),
        "question": (
            "заказ #557: сколько наблюдений ставки доказуемы НЕ из "
            "apy_composition_log.jsonl на днях знаменателя hit_rate, и что стои́т "
            "между наблюдением и записью"),
        "inputs": {
            "carrier_under_test": CARRIER_FILENAME,
            "independent_candidate": RUNS_FILENAME,
            "named_by_order": DIVERGENCE_FILENAME,
            "journal": JOURNAL_FILENAME,
        },
        "unreadable": [w for w in (carrier_why, runs_why, div_why, journal_why) if w],
        "independence": [],
        "run_axis": [],
        "comparable_axis": [],
        "mechanism": [],
        "outside_denominator": [],
        "findings": [],
        "advisory": (
            "прибор только считает; писатель журнала решений, писатель носителя, "
            "такт переписчика, max_runs буфера, POLLED_ADAPTERS, пины, "
            "MIN_HIT_RATE, TriggerParams, пороги RiskPolicy v1.0, потолки "
            "концентрации, стоп-кран и живой трек НЕ трогаются"),
    }

    denominator = scored_days(data_dir)
    runs, earliest_run, runs_parse_why = independent_runs(runs_doc)
    if runs_parse_why:
        doc["unreadable"].append(runs_parse_why)

    if denominator is None:
        doc["status"] = STATUS_UNMEASURED
        doc["counts"] = {"denominator_days": None}
        doc["findings"] = [
            "[НЕ ИЗМЕРЕНО] знаменатель hit_rate не ответил "
            "(shadow_trigger_eval.evaluate_window) — пустое множество сюда не "
            "подставляется: оно читалось бы как полное покрытие нуля"]
        return doc
    if not runs or earliest_run is None:
        doc["status"] = STATUS_UNMEASURED
        doc["counts"] = {"denominator_days": len(denominator)}
        doc["findings"] = [
            "[НЕ ИЗМЕРЕНО] независимого носителя прогонов нет на диске "
            f"({RUNS_FILENAME}) — числа наблюдений вне носителя не производится "
            "ни одного; ноль здесь был бы выдумкой"]
        return doc

    carrier = carrier_snapshots(carrier_rows)
    wakeups = carrier_wakeups(carrier_rows)
    side_a, pair_index = divergence_keys(div_rows)
    legs = journal_legs(journal_rows)
    margins = stability_margins(stability_doc)

    doc["independence"] = [
        independence_probe(carrier, side_a, DIVERGENCE_FILENAME),
        independence_probe(carrier, {d: set(v) for d, v in runs.items()},
                           RUNS_FILENAME),
    ]

    days = sorted(denominator)
    saturated = buffer_saturated(runs_doc)
    doc["buffer"] = {
        "saturated": saturated,
        "boundary_day": (earliest_run or "")[:10] or None,
        "note": ("буфер полон — граничный день срезан вытеснением, его число есть "
                 "нижняя граница" if saturated else
                 "буфер не полон — вытеснения не было, граничный день измерен целиком"
                 if saturated is False else
                 "НЕ ИЗМЕРЕНО: наполнение буфера не прочитано (нет `max_runs`) — "
                 "срез не приписывается"),
    }
    doc["run_axis"] = run_axis(days, carrier, runs, earliest_run, saturated)
    doc["comparable_axis"] = comparable_axis(days, legs, runs, margins,
                                             earliest_run, saturated)
    doc["mechanism"] = mechanism_axis(days, wakeups, runs, pair_index)

    # Слой 4 — контроль на НЕСВЯЗАННОМ населении, печатается последним.
    outside = sorted(set(carrier) - denominator)
    doc["outside_denominator"] = mechanism_axis(outside, wakeups, runs,
                                                pair_index)

    # Срезанный день ИЗМЕРЕН, просто неполно: его наблюдения доказаны и обязаны
    # считаться. Выкинуть его из счёта значило бы молча стереть доказанное —
    # ошибка в ту же сторону, что и выдать нижнюю границу за счёт, только зеркально.
    measured = [r for r in doc["run_axis"] if r["klass"] == DAY_MEASURED]
    boundary_rows = [r for r in doc["run_axis"]
                     if r["klass"] == DAY_BOUNDARY_TRUNCATED]
    countable = measured + boundary_rows
    judged = [p for p in doc["comparable_axis"] if p["klass"] == PAIR_JUDGED]
    doc["counts"] = {
        "denominator_days": len(denominator),
        "days_measured_by_independent": len(countable),
        "days_boundary_truncated": len(boundary_rows),
        "days_outside_independent_window": len(doc["run_axis"]) - len(countable),
        "days_touched_by_carrier": sum(1 for r in countable
                                       if r["carrier_snapshots"] > 0),
        "runs_provable_outside_carrier": sum(
            r["observations_outside_carrier"] or 0 for r in countable),
        "runs_provable_outside_carrier_is_floor": any(
            r["observations_outside_carrier"] for r in boundary_rows),
        "pairs_boundary_truncated": sum(
            1 for x in doc["comparable_axis"]
            if x["klass"] == PAIR_DAY_BOUNDARY_TRUNCATED),
        "pairs": len(doc["comparable_axis"]),
        "pairs_judged": len(judged),
        "runs_overwritten_before_transcription": sum(
            len(m["overwritten_before_transcription"]) for m in doc["mechanism"]),
    }
    doc["findings"] = _findings(doc)

    untouched_runs = sum(r["runs_provable"] for r in countable
                         if r["carrier_snapshots"] == 0)
    if untouched_runs:
        doc["status"] = STATUS_CRITICAL
    elif doc["unreadable"]:
        doc["status"] = STATUS_WARNING
    else:
        doc["status"] = STATUS_OK
    doc["overall"] = doc["status"]
    return doc


def format_report(doc: dict) -> List[str]:
    """Строки шага 0-офис. Порядок строк — порядок ВОПРОСА, и он обязателен.

    Сперва заголовок с числами покрытия, затем находки в том порядке, в каком их
    произвёл ``_findings``: независимость → ответ заказу → неизмеренное →
    пригодность → движение → механизм → контроль на несвязанном населении.
    Читатель, увидевший «ставка внутри дня двигалась на 4 парах» первой строкой,
    прочтёт это как замер всего знаменателя; строка про пригодность стои́т
    ПЕРЕД ней именно поэтому, и порядок закреплён тестом.
    """
    counts = doc.get("counts") or {}
    head = (f"   наблюдения вне носителя ставок (заказ #557): "
            f"{doc.get('status')} · знаменатель {counts.get('denominator_days')} дн. · "
            f"измерено независимым носителем {counts.get('days_measured_by_independent')} · "
            f"вне его окна {counts.get('days_outside_independent_window')} · "
            f"пар {counts.get('pairs')}, пригодных к сравнению "
            f"{counts.get('pairs_judged')}")
    out = [head]
    out.extend("   " + line for line in doc.get("findings", []))
    for line in doc.get("unreadable", []):
        out.append(f"   [ВХОД НЕ ПРОЧИТАН] {line}")
    out.append(
        "   НЕ ДОКЛАДЫВАЕТ: была ли у ноги живая ставка в прогоне, где она не "
        "была победителем — независимый носитель несёт на прогон РОВНО один "
        "протокол; и что происходило до начала кольцевого буфера — те дни "
        "неизмеримы по построению, а не пусты")
    out.append("   ADVISORY: " + str(doc.get("advisory")))
    return out


def run(root: Optional[str] = None, *, write: bool = True,
        now: Optional[datetime] = None) -> dict:
    base = Path(root) if root else Path(
        os.environ.get("SPA_DATA_DIR")
        or Path(__file__).resolve().parents[2] / "data")
    doc = build(base, now=now)
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(base / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = run(args.data_dir, write=not args.no_write)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    print(f"{doc['schema']} — {doc.get('status')}")
    for line in doc["findings"]:
        print("  " + line)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
