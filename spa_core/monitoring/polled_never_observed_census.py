"""Кого мы ОПРАШИВАЕМ и не слышали НИ РАЗУ — поимённо, с ценой (заказ #597, G11).

Заказ в хвосте [ADR-378] звучит так:

> Перепись протоколов, которые ОПРАШИВАЮТСЯ и при этом не имеют в ряду ни одной
> точки за всю его историю — поимённо, с длительностью молчания и с долей
> КАПИТАЛА книги, которая на них стои́т сегодня. Сегодня известен один такой
> (`pendle`), и известен он потому, что попался в слепом обороте; перепись
> отвечает, сколько их всего и не держит ли книга денег на протоколе, чья ставка
> не наблюдалась ни разу.

G6→G10 находили таких по одному и каждый раз СЛУЧАЙНО — нога всплывала в слепом
обороте отвергнутого дня. Вопрос «сколько их всего» до сих пор не задавал никто,
и пока он не задан, `pendle` неотличим от единственного исключения и от вершины
класса. Перепись отвечает прямо, и ответ решает, чинить поимённо или строить
правило.

## Что здесь считается наблюдением — и чем оно НЕ является

Наблюдение — точка в ``data/apy_series_daily.json``. Форму ряда разбирает ОДНО
место — :func:`journal_backfill_material.series_points` (то же требование, что у
[ADR-378]): вторая копия правила «что такое точка ряда» разошлась бы с первой
молча, и одна из копий назвала бы наблюдением то, что второй не является.

**Точка ряда НЕ есть эвиденс.** Накопитель кладёт значение, пропуская его
единственной проверкой на конечность, и провенанса `live` не несёт ([ADR-302]).
Поэтому «точек нет ни одной» доказывает СИЛЬНОЕ утверждение (живого числа у
производителя не появлялось), а «точки есть» — слабое (число было конечным, и
только). Направление доказательства здесь одностороннее, и сильная сторона —
отрицательная; ровно поэтому перепись строится на отсутствии, а не на наличии.

## Правило допуска накопителя измеряется, а не пересказывается

Накопитель берёт ``info.get("live_apy", info.get("apy"))`` — это **присутствие
КЛЮЧА**, а не истинность значения. Адаптер, несущий ``live_apy: null`` рядом с
конечным статическим ``apy``, в ряд НЕ попадает (и правильно: константа под
маркой `live` запрещена [ADR-053]). Адаптер, у которого ключа ``live_apy`` нет
ВОВСЕ, попадёт по ``apy`` — то есть статическая константа легла бы точкой в файл,
чья собственная подпись говорит «live APY percent points».

Перепись меряет оба класса у сегодняшнего производителя и докладывает их
раздельно. Замер 13.09: второй класс ПУСТ (0 адаптеров из 34), и это измеренный
ноль, а не отсутствие проверки — потолок назван, потолок сегодня не населён.
Сосед :func:`journal_backfill_material.provenance_exposure` описывает то же
правило словами «live_apy → иначе apy», и для ключа, лежащего со значением
``null``, это описание расходится с кодом накопителя: сосед счёл бы такой адаптер
допущенным, накопитель его отвергает. На ответ G11 расхождение не влияет (оно
работает в сторону строгости), но названо здесь, а не оставлено следующему.

## Шесть исходов, и они не сливаются (инв. #17)

По ОПРАШИВАЕМОМУ протоколу:

* ``observed`` — в ряду есть хотя бы одна разобранная точка;
* ``never_observed`` — ключа нет в ряду вовсе, при том что у производителя ряда
  он ЕСТЬ: накопителю его предъявляли, и он не принял ни одного числа. Это
  измеренное отсутствие, предмет заказа;
* ``series_row_unreadable`` — **НЕ ИЗМЕРЕНО**: ключ в ряду ЕСТЬ, а разобранных
  точек нет ни одной. Нечитаемая строка — не молчащий каждый день фид
  ([ADR-378], тот же исход);
* ``outside_producer`` — **НЕ ИЗМЕРЕНО**: опрашиваемого ключа нет у производителя
  ряда. Накопителю его не предъявляли, и «точек нет» не говорит о фиде ничего.

По КНИГЕ (деньги стоят там, где стоят, и спрашивать надо у них):

* ``book_key_polled`` — ключ книги опрашивается, его исход выше;
* ``book_key_not_polled`` — на ключе стоят деньги, а цикл его не опрашивает
  вовсе. Такой ключ спрашивается о ряде ОТДЕЛЬНО: наблюдался — находка, не
  наблюдался — деньги стоят на ставке, которой не видели ни разу.

## Длительность молчания меряется ОКНОМ РЯДА, а не ёмкостью кольца

Кольцо накопителя рассчитано на 800 дней (``_MAX_DAYS``), и его СОДЕРЖИМОЕ на
13.09 — 39 дат. Это разные числа, и подменять второе первым нельзя: «не звучал
800 дней» утверждало бы знание о 761 дне, которых в файле не было никогда.
Молчание считается по датам, на которых ряд принял точку ХОТЬ ОТ КОГО-ТО, а этот
протокол — нет; всё, что до первой даты окна, докладывается отдельным полем
``unmeasured_before`` и в счёт молчания не идёт.

> Поправка к прозе [ADR-378] (она моя же, циклом раньше): там сказано «ни одной
> точки в накопителе за всю его 800-дневную историю». Ёмкость кольца — 800 дней,
> история — 39; вывод про `pendle` от этого не меняется, а число обязано быть
> замером, а не константой из соседнего текста.

## Третий исход

Ряд не прочитан · производитель не прочитан · книга не прочитана · список
опрашиваемых не импортируется ⇒ ``UNMEASURED`` с названной причиной. «Опрашиваемых
без наблюдений НЕТ» и «спросить было нечем» — разные ответы, и второй за первый
не выдаётся.

## ADVISORY

``POLLED_ADAPTERS``, пины, накопитель ряда, писатель журнала, адаптер `pendle`,
``_fundable()``, пороги RiskPolicy v1.0, стоп-кран, живой трек и ``landing/`` НЕ
трогаются. Прибор только ЧИТАЕТ и называет имена, дни и доллары.
"""
from __future__ import annotations

import logging
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from spa_core.monitoring import journal_backfill_material as _jbm
from spa_core.utils.observation import observed

log = logging.getLogger(__name__)

OUTPUT_FILENAME = "polled_never_observed_census.json"
VERSION = "polled-never-observed-census-v1"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

SERIES_FILENAME = "apy_series_daily.json"
PRODUCER_FILENAME = "adapter_status.json"
BOOK_FILENAME = "current_positions.json"

# ── исходы по опрашиваемому протоколу ────────────────────────────────────
OUT_OBSERVED = "observed"
OUT_NEVER_OBSERVED = "never_observed"
OUT_ROW_UNREADABLE = "series_row_unreadable"
OUT_OUTSIDE_PRODUCER = "outside_producer"

#: Исход, при котором наблюдений НЕТ и это ИЗМЕРЕНО (доказательство в минус).
PROVEN_SILENT = (OUT_NEVER_OBSERVED,)
#: Исходы, при которых сказать нечего. Нулём они НЕ становятся (инв. #17).
UNMEASURED_OUTCOMES = (OUT_ROW_UNREADABLE, OUT_OUTSIDE_PRODUCER)

# ── исходы по ключу книги ────────────────────────────────────────────────
BOOK_POLLED = "book_key_polled"
BOOK_NOT_POLLED = "book_key_not_polled"

_ADVISORY = ("POLLED_ADAPTERS, пины, накопитель ряда, писатель журнала, адаптер "
             "pendle, _fundable(), пороги RiskPolicy v1.0, стоп-кран, живой трек "
             "и landing/ НЕ трогаются — прибор только ЧИТАЕТ и называет имена, "
             "дни и доллары")

#: Границы утверждения — В АРТЕФАКТ, а не только в шапку модуля: читатель отчёта
#: шапку не открывает, а именно он переносит число в решение о починке.
WHAT_IT_DOES_NOT_PROVE = [
    "не утверждает, что у молчащего протокола живой ставки НЕ СУЩЕСТВУЕТ в мире: "
    "измерено, что её не принял НАШ накопитель — это утверждение о нашей "
    "проводке, а не о протоколе",
    "не доказывает `live`-провенанс у наблюдённых: точка ряда проходит проверкой "
    "на конечность и провенанса не несёт (ADR-302). Сильная сторона вывода — "
    "отрицательная, и перепись стои́т на отсутствии, а не на наличии",
    "не говорит, существовал ли ключ у производителя в КАЖДЫЙ день окна: снимок "
    "`adapter_status.json` описывает сегодня, и состав прошлых дней прибор не "
    "домысливает — поэтому длительность молчания есть длительность окна ряда, а "
    "не доказанный возраст поломки",
    "не судит о днях до первой даты окна: до появления накопителя не измерено "
    "ничего, и ёмкость кольца (800 дней) историей не является",
    "не пересчитывает вердикты `_fundable()` и не двигает капитал: перепись "
    "называет, различимы ли для гейта «ставка протухла» и «ставки не было "
    "никогда», а различать ли их — решение отдельное",
    "не выводит родство ключей из похожести имён: `pendle` и `pendle_pt_susde` "
    "здесь РАЗНЫЕ объекты, и слияние их перевернуло бы ответ (ADR-378)",
]

# ── причины третьего исхода ──────────────────────────────────────────────
NO_POLLED = ("список `POLLED_ADAPTERS` не импортируется — население переписи "
             "неизвестно, и «молчащих нет» сказать нечем")
NO_SERIES = (f"`{SERIES_FILENAME}` не прочитан или не той формы — истории "
             "наблюдений нет, а «не прочитан» не читается как «фид молчал»")
NO_PRODUCER = (f"`{PRODUCER_FILENAME}` не прочитан или не той формы — вселенная "
               "производителя ряда неизвестна, и отличить «не приняли ни одного "
               "числа» от «ключа не предъявляли» нечем")
NO_BOOK = (f"`{BOOK_FILENAME}` не прочитан или в нём нет карты `positions` — "
           "цена молчания в долларах не измерена, и ноль вместо неё был бы "
           "ответом «денег на молчащих нет», которого никто не мерил")


def _is_finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _read_json(path: Path):
    import json
    return json.loads(path.read_text())


def polled_universe() -> List[Tuple[str, str]]:
    """``[(ключ, тир), …]`` — то, что цикл РЕАЛЬНО опрашивает.

    Берётся из кода (`POLLED_ADAPTERS`), а не из `data/*.json`: население заказа —
    «кого мы опрашиваем», и единственный источник этого факта — список, по
    которому идёт оркестратор. Рядом живут ещё два набора с другим составом
    (`ADAPTER_REGISTRY` 36, `ADAPTER_METADATA` 22, правило `.claude/rules/adapters.md`),
    и сверять перепись по ним значило бы ответить на чужой вопрос.
    """
    from spa_core.orchestrator.adapter_orchestrator import POLLED_ADAPTERS
    return [(str(k), str(t)) for k, t, _cls in POLLED_ADAPTERS]


def series_window(points: Dict[str, Dict[str, float]]) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Границы и полный список дат окна ряда — по ВСЕМ ключам сразу.

    Молчание одного протокола меряется днями, в которые ряд принял точку хоть от
    кого-то: день, когда не писал никто, — это молчание накопителя, а не фида
    конкретного протокола, и записывать его протоколу в долг было бы враньём в
    сторону тревоги.
    """
    dates: Set[str] = set()
    for pts in points.values():
        dates.update(pts)
    if not dates:
        return None, None, []
    ordered = sorted(dates)
    return ordered[0], ordered[-1], ordered


def classify(protocol: str, *, points: Dict[str, Dict[str, float]],
             producer: Set[str]) -> str:
    """Исход по одному опрашиваемому протоколу. Ничего не достраивает.

    Порядок ветвлений существен. Ключ, лежащий в ряду с нулём РАЗОБРАННЫХ точек,
    обязан стать НЕ ИЗМЕРЕНО раньше, чем сработает проверка производителя: иначе
    нечитаемая строка (наш дефект разбора) была бы записана фиду как молчание.
    """
    pts = points.get(protocol)
    if pts:
        return OUT_OBSERVED
    if pts is not None:
        # Ключ в ряду ЕСТЬ (`series_points` оставляет пустой словарь), а
        # разобранных точек нет ни одной — это про читаемость, не про фид.
        return OUT_ROW_UNREADABLE
    if protocol in producer:
        return OUT_NEVER_OBSERVED
    return OUT_OUTSIDE_PRODUCER


def _load_series(data_dir: Path) -> Optional[Dict[str, Dict[str, float]]]:
    """``{ключ: {дата: значение}}`` через ЕДИНСТВЕННЫЙ разборщик формы ряда."""
    try:
        raw = _read_json(data_dir / SERIES_FILENAME)
    except Exception as exc:  # noqa: BLE001
        log.warning("polled_never_observed_census: %s не прочитан (%s)",
                    SERIES_FILENAME, exc)
        return None
    if not isinstance(raw, dict):
        return None
    series = observed(raw, "series", kind=dict)
    if series is None:
        return None
    return _jbm.series_points(series)


def _load_producer(data_dir: Path) -> Optional[Set[str]]:
    try:
        raw = _read_json(data_dir / PRODUCER_FILENAME)
    except Exception as exc:  # noqa: BLE001
        log.warning("polled_never_observed_census: %s не прочитан (%s)",
                    PRODUCER_FILENAME, exc)
        return None
    if not isinstance(raw, dict):
        return None
    adapters = observed(raw, "adapters", kind=dict)
    if adapters is None:
        return None
    return {str(k) for k in adapters}


def admission_rule_exposure(data_dir: Path) -> dict:
    """Форма правила допуска накопителя на СЕГОДНЯШНЕМ снимке производителя.

    Меряется ровно то, что делает код накопителя — ``get("live_apy", get("apy"))``,
    то есть присутствие КЛЮЧА, — и результат делится на два класса, которые
    сливать нельзя: ключ лежит со значением ``null`` (накопитель отвергает) и
    ключа нет вовсе (накопитель допустит статическую константу под подписью
    «live»). Второй класс — потолок, и пустой потолок обязан быть ИЗМЕРЕННЫМ
    нулём, а не отсутствием строки в отчёте.
    """
    try:
        raw = _read_json(data_dir / PRODUCER_FILENAME)
        adapters = observed(raw, "adapters", kind=dict) if isinstance(raw, dict) else None
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"{PRODUCER_FILENAME} не прочитан ({exc})"}
    if adapters is None:
        return {"measured": False,
                "reason": f"в {PRODUCER_FILENAME} нет карты `adapters`"}
    live_finite: List[str] = []
    key_null_static: List[str] = []
    key_absent_static: List[str] = []
    for name, info in adapters.items():
        if not isinstance(info, dict):
            continue
        if "live_apy" not in info:
            if _is_finite(info.get("apy")):
                key_absent_static.append(str(name))
            continue
        if _is_finite(info.get("live_apy")):
            live_finite.append(str(name))
        elif _is_finite(info.get("apy")):
            key_null_static.append(str(name))
    return {
        "measured": True,
        "adapters_seen": len(adapters),
        "live_apy_finite": len(live_finite),
        "key_null_finite_apy_REFUSED": sorted(key_null_static),
        "key_absent_finite_apy_ADMITTED": sorted(key_absent_static),
        "rule": ('накопитель: info.get("live_apy", info.get("apy")) — присутствие '
                 'КЛЮЧА, не истинность значения'),
        "note": ("второй класс — потолок: попав в ряд, статическая константа "
                 "легла бы точкой в файл с подписью «live APY percent points». "
                 "Сегодня класс пуст, и это ИЗМЕРЕННЫЙ ноль"),
    }


def measure(data_dir: Path, *, now: Optional[datetime] = None) -> dict:
    """Собрать перепись. Любой недостающий вход ⇒ ``UNMEASURED`` с причиной."""
    data_dir = Path(data_dir)
    doc: dict = {
        "version": VERSION,
        "generated_at": (now or datetime.now().astimezone()).isoformat(),
        "question": ("какие ОПРАШИВАЕМЫЕ протоколы не имеют в ряду ни одной "
                     "точки за всю его историю — поимённо, с длительностью "
                     "молчания и долей капитала книги на них сегодня "
                     "(заказ #597/G11 приказа «Portfolio CIO»)"),
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
        "advisory": _ADVISORY,
    }

    def refuse(reason: str) -> dict:
        doc["status"] = STATUS_UNMEASURED
        doc["answer"] = {"measured": False, "reason": reason}
        doc["findings"] = [f"[НЕ ИЗМЕРЕНО] {reason}"]
        return doc

    try:
        polled = polled_universe()
    except Exception as exc:  # noqa: BLE001
        return refuse(f"{NO_POLLED} ({exc})")
    if not polled:
        return refuse(f"{NO_POLLED} (список пуст)")

    points = _load_series(data_dir)
    if points is None:
        return refuse(NO_SERIES)
    producer = _load_producer(data_dir)
    if producer is None:
        return refuse(NO_PRODUCER)

    book_raw: Optional[dict]
    try:
        book_raw = _read_json(data_dir / BOOK_FILENAME)
    except Exception as exc:  # noqa: BLE001
        return refuse(f"{NO_BOOK} ({exc})")
    positions = observed(book_raw, "positions", kind=dict) if isinstance(book_raw, dict) else None
    if positions is None:
        return refuse(NO_BOOK)
    funded: Dict[str, float] = {str(k): float(v) for k, v in positions.items()
                                if _is_finite(v)}
    deployed = round(sum(funded.values()), 2)

    win_lo, win_hi, all_dates = series_window(points)
    if win_lo is None:
        return refuse(f"{NO_SERIES} — в ряду нет ни одной разобранной точки ни у "
                      "кого, окна молчания не существует")

    per_protocol: List[dict] = []
    outcome_counts: Dict[str, int] = {OUT_OBSERVED: 0, OUT_NEVER_OBSERVED: 0,
                                      OUT_ROW_UNREADABLE: 0, OUT_OUTSIDE_PRODUCER: 0}
    for key, tier in polled:
        outcome = classify(key, points=points, producer=producer)
        outcome_counts[outcome] += 1
        pts = points.get(key) or {}
        dates = sorted(pts)
        row = {
            "protocol": key,
            "tier": tier,
            "outcome": outcome,
            "points": len(dates),
            "first_point": dates[0] if dates else None,
            "last_point": dates[-1] if dates else None,
            "book_usd": round(funded.get(key, 0.0), 2),
            "book_pct_of_deployed": (round(100.0 * funded[key] / deployed, 2)
                                     if key in funded and deployed else None),
        }
        if outcome in PROVEN_SILENT:
            # Молчание — дни окна, в которые ряд принял точку ХОТЬ ОТ КОГО-ТО.
            row["silent_days"] = len(all_dates)
            row["silence_window"] = {"from": win_lo, "to": win_hi}
            row["unmeasured_before"] = win_lo
        per_protocol.append(row)

    polled_keys = {k for k, _t in polled}
    book_rows: List[dict] = []
    for key, usd in sorted(funded.items()):
        # Ключ книги спрашивается о ряде НЕЗАВИСИМО от того, опрашивается ли он:
        # деньги стоят там, где стоят, и вопрос «видели ли мы эту ставку» к ним
        # относится одинаково в обоих случаях.
        book_outcome = BOOK_POLLED if key in polled_keys else BOOK_NOT_POLLED
        series_outcome = classify(key, points=points, producer=producer)
        book_rows.append({
            "protocol": key,
            "usd": round(usd, 2),
            "pct_of_deployed": round(100.0 * usd / deployed, 2) if deployed else None,
            "book_outcome": book_outcome,
            "series_outcome": series_outcome,
        })

    silent = [r for r in per_protocol if r["outcome"] in PROVEN_SILENT]
    unmeasured_rows = [r for r in per_protocol if r["outcome"] in UNMEASURED_OUTCOMES]
    silent_usd = round(sum(r["book_usd"] for r in silent), 2)
    # Деньги на ключе, который цикл не опрашивает И который в ряду не наблюдался.
    book_blind = [r for r in book_rows
                  if r["book_outcome"] == BOOK_NOT_POLLED
                  and r["series_outcome"] != OUT_OBSERVED]
    book_blind_usd = round(sum(r["usd"] for r in book_blind), 2)

    doc["population"] = {
        "polled": len(polled),
        "producer_keys": len(producer),
        "series_keys": len(points),
        "book_keys": len(funded),
        "deployed_usd": deployed,
        "outcomes": dict(outcome_counts),
    }
    doc["series_window"] = {"from": win_lo, "to": win_hi, "dates": len(all_dates),
                            "ring_capacity_days": 800,
                            "note": ("ёмкость кольца и его содержимое — РАЗНЫЕ "
                                     "числа; молчание меряется содержимым")}
    doc["per_protocol"] = per_protocol
    doc["book"] = book_rows
    doc["admission_rule"] = admission_rule_exposure(data_dir)
    doc["answer"] = {
        "measured": True,
        "never_observed": [r["protocol"] for r in silent],
        "never_observed_count": len(silent),
        "never_observed_usd": silent_usd,
        "never_observed_pct_of_deployed": (round(100.0 * silent_usd / deployed, 2)
                                           if deployed else None),
        "unmeasured_count": len(unmeasured_rows),
        "book_blind_keys": [r["protocol"] for r in book_blind],
        "book_blind_usd": book_blind_usd,
        "deployed_usd": deployed,
    }
    doc["status"] = _status(doc)
    doc["findings"] = _findings(doc)
    return doc


def _status(doc: dict) -> str:
    """CRITICAL — только когда на ненаблюдённой ставке СТОЯТ деньги.

    Различение существенно и намеренно не завышено: молчащий протокол без денег —
    дефект проводки (WARNING), молчащий протокол под капиталом — дефект решения о
    деньгах (CRITICAL). Свести их к одному цвету значило бы либо утопить второй,
    либо звонить набатом там, где сегодня не потеряно ничего.

    Числа берутся ПРЯМЫМ ключом, а не `.get(...) or 0`: подстановка нуля сделала
    бы «ключа нет» неотличимым от «измерено и равно нулю» (инв. #17) у того самого
    счёта, который решает вердикт.
    """
    ans = doc["answer"]
    if ans["never_observed_usd"] > 0 or ans["book_blind_usd"] > 0:
        return STATUS_CRITICAL
    if ans["never_observed_count"] > 0 or ans["unmeasured_count"] > 0:
        return STATUS_WARNING
    return STATUS_OK


def _findings(doc: dict) -> List[str]:
    ans = doc["answer"]
    pop = doc["population"]
    win = doc["series_window"]
    out: List[str] = []

    out.append(
        f"[ОТВЕТ] опрашиваемых протоколов {pop['polled']}; без единой точки в "
        f"ряду за всю его историю — {ans['never_observed_count']} "
        f"({', '.join(ans['never_observed']) or '—'}); капитал книги на них "
        f"сегодня ${ans['never_observed_usd']:,.2f} из ${ans['deployed_usd']:,.2f} "
        f"развёрнутых = {ans['never_observed_pct_of_deployed']} %")
    out.append(
        "[СТАТУС ЧИСЛА] вывод односторонний: «точек нет» доказывает, что живого "
        "числа накопитель не принимал ни разу; «точки есть» НЕ доказывает "
        "`live`-провенанс (ADR-302). Перепись стои́т на отсутствии — на сильной "
        "стороне")
    out.append("[ПО ИСХОДАМ] " + " · ".join(
        f"{k}={pop['outcomes'][k]}" for k in
        (OUT_OBSERVED, OUT_NEVER_OBSERVED, OUT_ROW_UNREADABLE, OUT_OUTSIDE_PRODUCER)))

    for r in doc["per_protocol"]:
        if r["outcome"] == OUT_OBSERVED:
            continue
        if r["outcome"] in PROVEN_SILENT:
            out.append(
                f"[ПОИМЁННО] {r['protocol']} [{r['tier']}]: точек 0 за всё окно "
                f"{r['silence_window']['from']}..{r['silence_window']['to']} "
                f"({r['silent_days']} дн., в каждый из них ряд принял точку от "
                f"кого-то другого); капитал книги ${r['book_usd']:,.2f}; до "
                f"{r['unmeasured_before']} НЕ ИЗМЕРЕНО — накопителя не было")
        else:
            out.append(
                f"[НЕ ИЗМЕРЕНО] {r['protocol']} [{r['tier']}]: исход "
                f"`{r['outcome']}` — точек нет, но сказать о фиде нечего")

    if ans["never_observed_usd"] > 0:
        out.append(
            f"[CRITICAL] книга держит ${ans['never_observed_usd']:,.2f} на "
            f"протоколе, чья ставка не наблюдалась НИ РАЗУ: "
            f"{', '.join(ans['never_observed'])}")
    if ans["book_blind_usd"] > 0:
        out.append(
            f"[CRITICAL] ${ans['book_blind_usd']:,.2f} стоят на ключах, которые "
            f"цикл не опрашивает вовсе и которых нет в ряду: "
            f"{', '.join(ans['book_blind_keys'])}")
    if ans["never_observed_count"] > 0 and ans["never_observed_usd"] == 0:
        out.append(
            "[ОПОРА] на молчащих сегодня не стои́т ни доллара — это ИЗМЕРЕННЫЙ "
            "ноль, а не отсутствие проверки. Срочности для денег нет; дефект "
            "проводки остаётся, и вчерашняя книга его уже оплачивала")

    adm = doc["admission_rule"]
    if adm.get("measured"):
        admitted = adm["key_absent_finite_apy_ADMITTED"]
        # Строка собирается ДО f-строки намеренно: выражение с вложенными
        # кавычками и переносом внутри `{…}` разбирается только с Python 3.12,
        # а CI держит ещё и 3.11 — «зелено у меня» не есть зелено там.
        admitted_txt = ", ".join(admitted) if admitted else "класс пуст — измеренный ноль"
        out.append(
            f"[ОПОРА] правило допуска накопителя — присутствие КЛЮЧА, не "
            f"истинность значения: адаптеров {adm['adapters_seen']}, с конечным "
            f"live_apy {adm['live_apy_finite']}, отвергнуто по `live_apy: null` "
            f"{len(adm['key_null_finite_apy_REFUSED'])}, ДОПУЩЕНО БЫ по "
            f"отсутствию ключа {len(admitted)} ({admitted_txt})")
    else:
        out.append(f"[НЕ ИЗМЕРЕНО] правило допуска накопителя: {adm.get('reason')}")

    out.append(
        f"[ОПОРА] окно ряда {win['from']}..{win['to']} — {win['dates']} дат при "
        f"ёмкости кольца {win['ring_capacity_days']} дн.; длительность молчания "
        f"есть длина ОКНА, а не возраст поломки, и до {win['from']} не измерено "
        f"ничего")
    out.append(
        f"[ОПОРА] вселенная производителя {pop['producer_keys']} ключ(ей), в ряду "
        f"{pop['series_keys']}, в книге {pop['book_keys']} — «ключа не "
        f"предъявляли» и «числа не приняли» разведены, а не слиты")
    out.append(f"ADVISORY: {_ADVISORY}")
    return out


def format_report(doc: dict) -> List[str]:
    # Прямой ключ: `findings` ставит КАЖДАЯ ветка `measure`, включая отказ, —
    # поэтому его отсутствие есть чужая ошибка формы, а не пустой отчёт, и
    # подставлять вместо неё пустой список значило бы печатать тишину как
    # чистый прогон (инв. #17).
    return list(doc["findings"])


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, **kwargs) -> dict:
    """Форма, которую ждут ступень переписей `findings_bridge` и шаг 0-офис."""
    from spa_core.utils.atomic import atomic_save

    root = root or str(Path(__file__).resolve().parents[2])
    data_dir = Path(root) / "data"
    doc = measure(data_dir, now=now, **kwargs)
    findings = list(doc["findings"])
    doc["overall"] = doc["status"]
    doc["counts"] = {
        "critical": sum(1 for x in findings if x.startswith("[CRITICAL]")),
        "warn": sum(1 for x in findings if x.startswith("[WARNING]")),
        "info": sum(1 for x in findings if x.startswith("[ОТВЕТ")
                    or x.startswith("[СТАТУС ЧИСЛА]") or x.startswith("[ПО ИСХОДАМ]")
                    or x.startswith("[ПОИМЁННО]") or x.startswith("[ОПОРА]")),
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
        description=("кого мы ОПРАШИВАЕМ и не слышали ни разу: перепись "
                     "протоколов без единой точки в ряду APY, с длительностью "
                     "молчания и долей капитала книги "
                     "(заказ #597/G11 приказа «Portfolio CIO»)"))
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
