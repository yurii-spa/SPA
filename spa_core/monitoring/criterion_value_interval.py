"""ИНТЕРВАЛ значения критерия ``hit_rate`` при знаменателе 19 вместо 16 (заказ #600/G14).

Заказ, оставленный в хвосте [ADR-381] по стоячему приказу владельца «Portfolio CIO»
(`nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md`):

> Ряд G6→G13 мерил ЦЕНУ починок; ОТДАЧУ не мерил ни один. Назвать ИНТЕРВАЛ значения
> критерия при знаменателе 19 вместо 16 — обеими границами и НИ ОДНИМ числом между
> ними: три материальных дня дают вердикт настоящими ставками, без сентинела, а
> остальные остаются ``unmeasured`` и входят в интервал обеими сторонами. Середина
> была бы ровно тем, против чего писан [ADR-300].

## Предмет ровно один

**Значение критерия ``hit_rate``, посчитанное на знаменателе 19, — ДВУМЯ границами.**
Не размер знаменателя (предмет ``hit_rate_denominator_recovery``, заказ #591). Не доля
населения (предмет ``criterion_population_floor``, заказ #599). Не доллары оборота и не
цена ноги в днях. Все эти числа приходят СЮДА от их производителей и здесь не
пересчитываются.

## Почему значение печатать теперь МОЖНО, хотя семь заказов подряд было нельзя

[ADR-300] запрещает печатать вердикт дня, поднятого **под сентинелом**: исход ``hit``
такого дня есть артефакт подставленного нуля, а не наблюдение. Запрет — про СЕНТИНЕЛ,
а не про само слово «значение», и снимается он ровно тогда, когда сентинела нет.

G10 ([ADR-378]) измерил, что у трёх из восьми слепых дней **материал в истории фидов
существует**: в ряду ``apy_series_daily.json`` есть точка нужного форвардного дня под
нужным ключом. Значит этим дням можно выдать не ноль, а **настоящую наблюдённую
ставку того самого дня**, и полученный вердикт будет наблюдением, а не артефактом.
Дню, у которого точки ряда нет, не выдаётся НИЧЕГО — он остаётся неразрешённым и
входит в интервал ОБЕИМИ сторонами.

Отсюда форма ответа, которую заказ и потребовал:

* **нижняя граница** — все неразрешённые дни считаются ``miss``;
* **верхняя граница** — все неразрешённые дни считаются ``hit``;
* **середины нет ни одной**, и это не осторожность: любое число между границами
  означало бы, что про неразрешённый день что-то известно. Не известно ничего.

## Знаменатель ЧУЖОЙ и берётся ПО ИМЕНИ

19 — ступень ``our_code_floor`` лестницы соседа ([ADR-381]), и своего знаменателя у
этого прибора нет ни одного. Но взять чужое число на веру мало: тот же 19 получается
здесь ВТОРОЙ машинерией — настоящим реплеем судьи по записям, которым выданы
материальные ставки. Разошлись ⇒ **НЕ ИЗМЕРЕНО**, и победитель не выбирается: какая из
двух машинерий неверна, прибор не знает.

## Нулевая ширина — ИЗМЕРЕННЫЙ исход, а не отсутствие интервала

Если материал разрешил все три дня, границы совпадают, и интервал вырождается в точку.
Это законный ответ (инв. #17: «измерено и равно нулю» обязано отличаться от «не
измерено»), но только при условии, что прибор ВООБЩЕ способен разойтись. Иначе нулевая
ширина — вакуум: неотличимо «все дни разрешились» от «прибор никогда не расходится».
Поэтому внутри замера гоняется **контроль способности**: тот же расчёт с изъятым
материалом у ног ОДНОГО названного дня обязан дать ширину больше нуля. Не дал ⇒
**НЕ ИЗМЕРЕНО**.

## Единицы сверяются, потому что ошибка в них подделала бы КАЖДЫЙ вердикт

Журнал и ряд — два разных производителя одной величины, а `.claude/rules/adapters.md`
прямо предупреждает: часть адаптеров отдаёт проценты, часть — доли. Смешать шкалы
значило бы выдать ставку 3.3 % за 330 % и получить вердикты, выглядящие измеренными.
Поэтому на парах, наблюдённых ОБОИМИ производителями, сверяется медианное отношение;
пустое пересечение и отношение вне полосы дают **НЕ ИЗМЕРЕНО**, а не «шкала та же».

## Что отвечает заказу про ОТДАЧУ

Отдача починки — это не «насколько вырастет число», а **меняется ли от неё РЕШЕНИЕ**.
Критерий взвода сравнивается с ``MIN_HIT_RATE`` (порог владельца, [ADR-067]), и потому
прибор печатает вердикт порога на ОБЕИХ границах. Совпали ⇒ решение к починке
НЕЧУВСТВИТЕЛЬНО, и вся её ценность лежит в ПОКРЫТИИ населения, а не в значении.
Разошлись ⇒ починка способна перевернуть взвод, и её место в очереди — первое.

**ADVISORY.** Прибор ЧИТАЕТ. ``hit_rate``, ``MIN_HIT_RATE``, ``TriggerParams``, писатель
журнала, ``POLLED_ADAPTERS``, пины, адаптеры, накопитель ряда, пороги RiskPolicy v1.0,
стоп-кран, живой трек и ``landing/`` не трогаются; капитал не двигается.

[ADR-067]: docs/decisions/ADR-067-shadow-trigger-arming.md
[ADR-300]: docs/decisions/ADR-300-no-verdict-under-sentinel.md
[ADR-378]: docs/decisions/ADR-378-writer-universe-lever-floor.md
[ADR-381]: docs/decisions/ADR-381-criterion-population-floor.md
"""
# LLM_FORBIDDEN
from __future__ import annotations

import copy
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Sequence, Set, Tuple

# Соседи зовутся ПО ССЫЛКЕ НА МОДУЛЬ, а не связанными при импорте именами: связанное имя
# есть СНИМОК функции на момент импорта, и подмена канонического правила прошла бы мимо
# нас молча. Так же поступают все соседи по этому заказу (ADR-366/368/369/371/378/380/381).
from spa_core.monitoring import criterion_population_floor as _cpf
from spa_core.monitoring import hit_rate_denominator_recovery as _rec
from spa_core.monitoring import journal_backfill_material as _jbm
from spa_core.monitoring import unobserved_leg_remedy_class as _remedy
from spa_core.paper_trading import shadow_trigger_eval as _ste
from spa_core.utils.observation import observed

log = logging.getLogger("spa.monitoring.criterion_value_interval")

OUTPUT_FILENAME = "criterion_value_interval.json"
VERSION = "criterion-value-interval-v1"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

SERIES_FILENAME = "apy_series_daily.json"

#: Ступень лестницы соседа, о знаменателе которой спрашивает заказ. Литерал назван ОДИН
#: раз: вторая копия разошлась бы с оригиналом молча при переименовании у соседа.
RUNG_OUR_CODE = _cpf.RUNG_OUR_CODE

#: Полоса, внутри которой медианное отношение «ряд / журнал» считается ОДНОЙ шкалой.
#: Перепутанные проценты и доли дают ×100 либо ×0.01 и в полосу не попадают никогда;
#: обычный разброс двух производителей одной ставки — единицы процентов.
UNIT_RATIO_LOW = 0.5
UNIT_RATIO_HIGH = 2.0

#: Сколько знаков у границ. Тот же округлитель, что у канонического `hit_rate`, —
#: иначе граница и опубликованное число спорили бы в последнем знаке.
RATE_DIGITS = 4

_ADVISORY = ("ADVISORY: `hit_rate`, `MIN_HIT_RATE`, `TriggerParams`, писатель журнала, "
             "`POLLED_ADAPTERS`, пины, адаптеры, накопитель ряда, пороги RiskPolicy "
             "v1.0, стоп-кран и живой трек НЕ трогаются — прибор только считает "
             "значение критерия ДВУМЯ границами на чужом знаменателе")

#: Границы утверждения едут В АРТЕФАКТЕ, а не только в шапке модуля: читатель отчёта
#: шапку не открывает, а именно он переносит границы в решение об очереди починок.
WHAT_IT_DOES_NOT_PROVE = [
    "не печатает НИ ОДНОГО числа между границами: середина означала бы, что про "
    "неразрешённый день что-то известно, а не известно ничего (ADR-300)",
    "не обещает, что вердикт разрешённого дня ВЕРЕН: он посчитан настоящей ставкой "
    "того дня, но правота HOLD прибором не пересчитывается и не утверждается",
    "не пересчитывает чужие числа: знаменатель 19 — ступень `our_code_floor` соседа "
    "ADR-381, потолок — соседа ADR-371, материал — соседа ADR-378; своего знаменателя "
    "у прибора нет ни одного",
    "не утверждает, что материальный день ПОДНЯЛСЯ БЫ в живой системе: точка ряда "
    "доказывает конечное число у производителя, а не провенанс `live` у писателя "
    "журнала (ADR-302) — направление доказательства одностороннее",
    "не меряет отдачу починки для ВТОРОГО критерия взвода (`net_bps_if_followed`): "
    "он про ACT-дни, и его население здесь не считается — сказано отдельной строкой, "
    "а не выведено из нашей",
    "не принимает ни строки у писателя, ни проводки ноги к фиду: и то и другое "
    "money-path и решение владельца",
]

# ── исходы, которые НЕ измеряются ────────────────────────────────────────────
NO_JOURNAL = ("журнал решений пуст или не прочитан — населения вопроса нет, и это НЕ "
              "«знаменатель нулевой»")
NO_POLLED = ("`POLLED_ADAPTERS` не прочитан — набор рычага писателя неизвестен; «не "
             "прочитан» не читается как «опрашивать нечего»")
NO_SERIES = (f"`{SERIES_FILENAME}` не прочитан или не той формы — материала нет, а «не "
             "прочитан» не читается как «фид молчал»")
NO_CANON = ("канонический `hit_rate` (`shadow_trigger_eval.evaluate_window`) не измерен "
            "— сверять свой числитель не с чем, а второе определение числителя заводить "
            "запрещено")
NO_LADDER = ("сосед `criterion_population_floor` не дал лестницы — знаменателя 19 "
             "неоткуда взять, и вычислять его самим значило бы завести второй")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _rate(numerator: int, denominator: int) -> Optional[float]:
    """Значение критерия либо ``None``. Нулевой знаменатель — НЕ нулевая ставка (инв. #17)."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, RATE_DIGITS)


# ── материал: ставки, а не отметки ───────────────────────────────────────────
def load_series_points(data_dir: Path) -> Optional[Dict[str, Dict[str, float]]]:
    """``{ключ: {дата: ставка}}`` из ряда фидов. ``None`` = НЕ ИЗМЕРЕНО.

    Форму ряда разбирает ``journal_backfill_material.series_points`` — то самое ОДНО
    место, которое держит правило «что такое точка ряда». Вторая копия правила
    разошлась бы с первой молча, и одна из двух назвала бы ставкой то, что второй
    ставкой не является.
    """
    try:
        doc = _jbm._read_json(Path(data_dir) / SERIES_FILENAME)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        log.warning("%s не прочитан: %s", SERIES_FILENAME, exc)
        return None
    series = observed(doc if isinstance(doc, dict) else {}, "series", kind=dict)
    if series is None:
        return None
    points = _jbm.series_points(series)
    return points or None


def unit_parity(records: Dict[str, dict],
                points: Dict[str, Dict[str, float]]) -> dict:
    """Одна ли шкала у журнала и у ряда — замер на парах, наблюдённых ОБОИМИ.

    Отношение берётся медианное, а не среднее: один выброс (а на живом замере 14.09
    максимальное расхождение пары — 7.35 п.п.) сдвинул бы среднее и превратил бы
    контроль шкалы в контроль выбросов. Предмет здесь — ПОРЯДОК величины.
    """
    ratios: List[float] = []
    pairs = 0
    for date, record in records.items():
        evidenced = observed(record, "apy_evidenced_pct", kind=dict) or {}
        for key, value in evidenced.items():
            if value is None or isinstance(value, bool):
                continue
            point = points.get(str(key), {}).get(date)
            if point is None:
                continue
            pairs += 1
            # Пара, где обе стороны нулевые, об отношении не говорит ничего и в
            # медиану не берётся: деление на ноль тут было бы отказом по форме, а не
            # наблюдением о шкале.
            if float(value) == 0.0:
                continue
            ratios.append(float(point) / float(value))
    if not ratios:
        return {"measured": False, "pairs": pairs,
                "reason": ("ни одной пары, наблюдённой обоими производителями, — шкалу "
                           "ряда сверить не с чем, а «не сверено» не есть «та же шкала»")}
    ratio = median(ratios)
    return {"measured": True, "pairs": pairs, "compared": len(ratios),
            "median_ratio": round(ratio, 6),
            "band": [UNIT_RATIO_LOW, UNIT_RATIO_HIGH],
            "passed": UNIT_RATIO_LOW <= ratio <= UNIT_RATIO_HIGH,
            "what_it_proves": ("журнал и ряд говорят в ОДНОЙ шкале; перепутанные "
                               "проценты и доли дали бы ×100 либо ×0.01 и в полосу не "
                               "попали бы никогда")}


# ── возмущение НАСТОЯЩИМИ ставками ───────────────────────────────────────────
def grant_material(records: Dict[str, dict], *, polled: Set[str],
                   twins: Dict[str, List[str]],
                   points: Dict[str, Dict[str, float]],
                   withhold: Sequence[str] = ()) -> Tuple[Dict[str, dict], List[dict]]:
    """Записи, которым выдан МАТЕРИАЛ — ставка того же дня из ряда фидов.

    Сентинела здесь нет ни одного, и в этом весь смысл заказа: выдаётся ровно то
    число, которое ряд наблюдал в ТОТ ЖЕ день под ТЕМ ЖЕ ключом, поэтому полученный
    вердикт есть наблюдение, а не артефакт подстановки (ADR-300).

    Рычаг близнецов берётся у соседа целиком (``hit_rate_denominator_recovery.perturb``
    с ``grant_twin``): близнец отдаёт ЖИВУЮ ставку той же записи, и вторая копия этого
    правила разошлась бы с оригиналом молча.

    ``withhold`` — ключи, которым материал НЕ выдаётся. Это не настройка, а инструмент
    контроля способности: изъяв материал у названных ног, прибор обязан разойтись
    границами, иначе нулевая ширина ничего не значит.

    Возвращает ``(записи, провенанс)``, где провенанс — по строке на КАЖДУЮ выданную
    ставку. Без него «ставка настоящая» было бы заявлением, а не измерением.
    """
    blocked = {str(k) for k in withhold}
    seeded = _rec.perturb(records, polled=polled, twins=twins, grant_polled=False,
                          respect_writer=True, grant_twin=True)
    out: Dict[str, dict] = {}
    provenance: List[dict] = []
    for date, record in seeded.items():
        clone = copy.deepcopy(record)
        apy = observed(clone, "apy_evidenced_pct", kind=dict)
        apy = dict(apy) if apy is not None else {}
        # Суждение писателя об эвиденсе УВАЖЕНО — это и есть рычаг писателя в чистом
        # виде, тот самый, по которому сосед считал ступень `our_code_floor`.
        # Перебить его значило бы считать другую ступень и сравнивать с не тем числом.
        for key in sorted((polled - _rec.writer_unevidenced_keys(clone)) - blocked):
            if apy.get(key) is not None:
                continue
            value = points.get(key, {}).get(date)
            if value is None:
                # Материала нет ⇒ не выдаётся НИЧЕГО. Ровно здесь проходит граница
                # между этим прибором и всеми семью предыдущими: они подставляли
                # сентинел, и потому не имели права печатать вердикт.
                continue
            apy[key] = value
            provenance.append({"cycle_date": date, "key": key, "rate_pct": value,
                               "source": f"{SERIES_FILENAME}:series[{key}][{date}]"})
        clone["apy_evidenced_pct"] = apy
        out[date] = clone
    return out, provenance


def provenance_is_material(provenance: Sequence[dict],
                           points: Dict[str, Dict[str, float]]) -> List[str]:
    """Выданные ставки, которых в ряду НЕТ. Пустой список = каждая ставка наблюдена.

    Контроль отвечает на вопрос «а точно ли без сентинела», и отвечает ИЗМЕРЕНИЕМ:
    заявление «мы подставляем только материал» проверяется обратным чтением каждой
    выданной ставки у того же производителя, а не доверием к ветке выше.
    """
    bad: List[str] = []
    for row in provenance:
        key, date = str(row.get("key")), str(row.get("cycle_date"))
        if points.get(key, {}).get(date) != row.get("rate_pct"):
            bad.append(f"{date}:{key}")
    return bad


def _outcomes(records: Dict[str, dict], horizon: int) -> Tuple[Dict[str, dict], Set[str]]:
    """``(строки судьи, знаменатель)`` — оба по каноническому правилу соседа."""
    rows = _rec._judge_all(records, horizon)
    return rows, {d for d, row in rows.items() if _rec.in_denominator(row)}


def _hits(rows: Dict[str, dict], days: Set[str]) -> Set[str]:
    """Числитель по правилу КАНОНИЧЕСКОГО производителя: ``outcome == "hit"``.

    Правило процитировано у ``shadow_trigger_eval.evaluate_window`` и сверяется с его
    же готовым числом ниже (контроль ПАРИТЕТ-ЧИСЛИТЕЛЬ): цитата без сверки была бы
    вторым определением числителя, а спор двух определений молчалив.
    """
    return {d for d in days if rows[d].get("outcome") == "hit"}


def measure(data_dir: Path, *, now: Optional[datetime] = None,
            horizon_days: Optional[int] = None, book_id: Optional[str] = None,
            ladder_doc: Optional[dict] = None, **_ignored) -> dict:
    """Ответ заказу #600: значение критерия на знаменателе 19 — ДВУМЯ границами.

    ``ladder_doc`` — точка инъекции для тестов: стенд подаёт лестницу соседа напрямую.
    ``_ignored`` — совместимость со ступенью переписей, которая передаёт общие для всех
    приборов ключи. Глотать их МОЛЧА безопасно ровно потому, что ни один не участвует в
    замере: появись здесь значащий параметр, он обязан быть назван явно.
    """
    data_dir = Path(data_dir)
    horizon = int(horizon_days or _ste.DEFAULT_HORIZON_DAYS)
    doc: dict = {
        "version": VERSION,
        "generated_at": (now or _utcnow()).isoformat(),
        "subject": ("значение критерия `hit_rate` на знаменателе ступени "
                    "`our_code_floor` — ДВУМЯ границами и ни одним числом между ними "
                    "(заказ #600/G14 приказа «Portfolio CIO»)"),
        "unit": "доля (значение критерия hit_rate), две границы; не дни и не доллары",
        "horizon_days": horizon,
        "status": STATUS_UNMEASURED,
        "findings": [],
        "advisory": _ADVISORY,
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
    }
    f: List[str] = doc["findings"]

    def refuse(reason: str) -> dict:
        doc["status"] = STATUS_UNMEASURED
        doc["unmeasured_reason"] = reason
        doc["answer"] = None
        f.append(f"[НЕ ИЗМЕРЕНО] {reason}")
        return doc

    # ── вход 1: журнал решений ───────────────────────────────────────────────
    try:
        history, bad_lines = _ste.load_history(data_dir, book_id)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        return refuse(f"{NO_JOURNAL} ({type(exc).__name__}: {exc})")
    if not history:
        return refuse(NO_JOURNAL)
    records = {str(r.get("cycle_date")): r for r in history}
    doc["journal"] = {"rows": len(history), "unparseable": bad_lines,
                      "days": len(records)}

    # ── вход 2: опрашиваемый набор и близнецы ────────────────────────────────
    polled = _remedy._polled_keys()
    if polled is None:
        return refuse(NO_POLLED)
    twins_doc = _remedy._twin_keys(data_dir)
    twins: Dict[str, List[str]] = twins_doc.get("pairs") or {}

    # ── вход 3: материал ─────────────────────────────────────────────────────
    points = load_series_points(data_dir)
    if points is None:
        return refuse(NO_SERIES)
    doc["series"] = {"keys": len(points),
                     "points": sum(len(v) for v in points.values())}

    # ── контроль ЕДИНИЦ (до единого вердикта) ────────────────────────────────
    units = unit_parity(records, points)
    doc["unit_parity"] = units
    if not units.get("measured"):
        return refuse(f"шкала ряда не сверена: {units.get('reason')}")
    if not units.get("passed"):
        return refuse(
            f"журнал и ряд говорят в РАЗНЫХ шкалах: медианное отношение "
            f"{units.get('median_ratio')} вне полосы "
            f"[{UNIT_RATIO_LOW}, {UNIT_RATIO_HIGH}] — выданные ставки подделали бы "
            f"каждый вердикт, и он выглядел бы измеренным")

    # ── вход 4: лестница соседа (знаменатель — ЧУЖОЙ) ────────────────────────
    if ladder_doc is None:
        try:
            ladder_doc = _cpf.measure(data_dir, now=now)
        except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
            return refuse(f"{NO_LADDER}: {type(exc).__name__}: {exc}")
    if (ladder_doc or {}).get("status") == STATUS_UNMEASURED:
        return refuse(f"{NO_LADDER}: {ladder_doc.get('unmeasured_reason')}")
    rungs = {str(r.get("rung")): r for r in (ladder_doc.get("ladder") or [])
             if isinstance(r, dict)}
    rung = rungs.get(RUNG_OUR_CODE)
    if rung is None or rung.get("denominator") is None:
        return refuse(f"{NO_LADDER}: ступени `{RUNG_OUR_CODE}` в лестнице нет")
    denominator = int(rung["denominator"])
    ladder_pop = observed(ladder_doc, "population", kind=dict) or {}
    expected_days = observed(ladder_pop, "days_recoverable_by_our_code_with_material",
                             kind=list)
    if expected_days is None:
        return refuse(f"{NO_LADDER}: сосед не назвал материальные дни нашего кода "
                      f"поимённо — сверять поднятые дни не с чем, а по мощности "
                      f"тождество наборов не проверяется")
    expected = {str(d) for d in expected_days}
    base_from_ladder = ladder_pop.get("denominator_today")
    # Ступень и перечень обязаны говорить об ОДНОМ населении. Равенство не наступает
    # по построению: ступень сосед считает ВЫЧИТАНИЕМ из потолка, а перечень —
    # разностью множеств, и разойтись они могут.
    if base_from_ladder is None or int(base_from_ladder) + len(expected) != denominator:
        return refuse(
            f"ступень `{RUNG_OUR_CODE}` ({denominator}) не равна сегодняшнему "
            f"знаменателю соседа ({base_from_ladder}) плюс его же материальным дням "
            f"({len(expected)}) — ступень и перечень про разные населения")
    doc["denominator_source"] = {
        "value": denominator,
        "rung": RUNG_OUR_CODE,
        "from": "criterion_population_floor (ADR-381)",
        "days_expected_to_lift": sorted(expected),
        "why_not_ours": ("своего знаменателя у прибора нет ни одного: пересчитать чужое "
                         "число значило бы завести второе определение того же населения"),
    }

    # ── базовая линия ────────────────────────────────────────────────────────
    base_rows, baseline = _outcomes(records, horizon)
    canon = _ste.scored_days(data_dir, horizon_days=horizon)
    if canon is None:
        return refuse(NO_CANON)
    if canon != baseline:
        return refuse(
            f"базовый знаменатель ({len(baseline)}) разошёлся с каноническим "
            f"({len(canon)}) — числам ниже верить нельзя")
    base_hits = _hits(base_rows, baseline)

    # ПАРИТЕТ-ЧИСЛИТЕЛЬ: моё «hit» обязано дать РОВНО опубликованный `hit_rate`.
    try:
        canon_report = _ste.evaluate_window(data_dir, write=False,
                                            horizon_days=horizon)
    except Exception as exc:  # noqa: BLE001 — любой отказ = «не измерено»
        return refuse(f"{NO_CANON}: {type(exc).__name__}: {exc}")
    canon_rate = canon_report.get("hit_rate")
    own_rate = _rate(len(base_hits), len(baseline))
    doc["numerator_parity"] = {
        "canonical_hit_rate": canon_rate,
        "own_hit_rate": own_rate,
        "hits_today": len(base_hits),
        "denominator_today": len(baseline),
        "passed": canon_rate is not None and own_rate == canon_rate,
        "what_it_proves": ("числитель отбирается ТЕМ ЖЕ правилом, что читает владелец "
                           "в карточке взвода; второе определение числителя спорило бы "
                           "с первым молча"),
    }
    if not doc["numerator_parity"]["passed"]:
        return refuse(
            f"мой числитель даёт {own_rate}, канонический `hit_rate` — {canon_rate}; "
            f"границы стояли бы на втором определении числителя")

    # Знаменатель ЧУЖОЙ, числитель СВОЙ — и оба обязаны стоять на одном населении.
    # Согласия ступени с её же перечнем для этого мало: сосед мог мерить другой журнал
    # или другой горизонт, и тогда доля собралась бы из числителя и знаменателя про
    # разное, выглядя при этом измеренной. Найдено положительным контролем: стенд с
    # расхождением 9 против 7 давал ответ, и ни один контроль не краснел.
    if int(base_from_ladder) != len(baseline):
        return refuse(
            f"сосед считает сегодняшний знаменатель равным {base_from_ladder}, а "
            f"канонический даёт {len(baseline)} — знаменатель ступени и мой числитель "
            f"стоят на РАЗНЫХ населениях")

    # ── возмущение МАТЕРИАЛОМ ────────────────────────────────────────────────
    granted, provenance = grant_material(records, polled=polled, twins=twins,
                                         points=points)
    fake = provenance_is_material(provenance, points)
    doc["provenance_control"] = {
        "grants": len(provenance),
        "not_found_in_series": fake[:10],
        "passed": not fake,
        "what_it_proves": ("каждая выданная ставка обратным чтением найдена в ряду тем "
                           "же ключом и той же датой — сентинела нет ни одного, и "
                           "потому запрет ADR-300 на печать вердикта здесь не действует"),
    }
    if fake:
        return refuse(f"{len(fake)} выданных ставок в ряду не найдено — «настоящая "
                      f"ставка» оказалась бы заявлением, а не измерением")
    doc["granted_rates"] = provenance

    granted_rows, granted_denominator = _outcomes(granted, horizon)

    # МОНОТОННОСТЬ: выдача ставок может только ДОБАВЛЯТЬ дни.
    lost = sorted(baseline - granted_denominator)
    doc["monotonicity_control"] = {
        "passed": not lost,
        "days_lost": lost[:10],
        "what_it_proves": ("выдача наблюдённых ставок не выбрасывает дни из "
                           "знаменателя; выпавший день означал бы, что возмущение "
                           "мерит не тот путь"),
    }
    if lost:
        return refuse(f"монотонность нарушена на {len(lost)} дн. — ответ недействителен")

    lifted = granted_denominator - baseline
    stranger = sorted(lifted - expected)
    # Сверка ОДНОСТОРОННЯЯ, и сторона выбрана не из осторожности, а по форме чисел:
    # ступень соседа получена ВЫЧИТАНИЕМ из потолка и есть ВЕРХНЯЯ граница достижимого
    # (материал — условие необходимое и не достаточное, ADR-302/ADR-378). Значит реплей
    # вправе поднять МЕНЬШЕ — именно этот недобор и есть источник интервала. А вот
    # поднять день, которого у соседа нет в материальном перечне, реплей права не имеет:
    # это две машинерии о разных населениях, и вот ЭТО улика.
    doc["ladder_parity"] = {
        "our_replay_denominator": len(granted_denominator),
        "neighbour_rung_denominator": denominator,
        "days_lifted": sorted(lifted),
        "days_expected": sorted(expected),
        "lifted_outside_neighbour": stranger,
        "passed": not stranger,
        "denominator_agreement": len(granted_denominator) == denominator,
        "direction": ("одностороннее: реплей вправе поднять меньше ступени соседа "
                      "(ступень — верхняя граница), но не вправе поднять чужой день"),
        "what_it_proves": ("две машинерии — вычитание из потолка у соседа и настоящий "
                           "реплей судьи здесь — говорят об ОДНОМ населении; поднятый "
                           "чужой день означал бы, что знаменатель и числитель про разное"),
    }
    if stranger:
        return refuse(
            f"реплей поднял дни вне материального перечня соседа "
            f"({', '.join(stranger)}) — две машинерии говорят о разных населениях")

    # ── границы ──────────────────────────────────────────────────────────────
    resolved = sorted(lifted)
    unresolved = sorted(expected - lifted)
    lifted_hits = _hits(granted_rows, lifted)
    # Числитель считается В ВОЗМУЩЁННОМ МИРЕ целиком: смешивать исходы двух миров
    # значило бы собрать долю, у которой части про разное. Насколько возмущение
    # сдвинуло исходы базовых дней — отдельная измеренная величина ниже.
    granted_base_hits = _hits(granted_rows, baseline)
    flipped = sorted(d for d in baseline
                     if granted_rows[d].get("outcome") != base_rows[d].get("outcome"))
    doc["baseline_stability"] = {
        "days_flipped": flipped,
        "count": len(flipped),
        "hits_today": len(base_hits),
        "hits_under_grant": len(granted_base_hits),
        "what_it_proves": ("сдвинул ли материал исход УЖЕ оценённых дней: выдача ставок "
                           "может сделать полностью оценённым более РАННИЙ форвардный "
                           "день, и вердикт базового дня сменится. Ноль здесь — "
                           "измеренный ноль, а не отсутствие проверки (инв. #17)"),
    }

    numerator_low = len(granted_base_hits) + len(lifted_hits)
    numerator_high = numerator_low + len(unresolved)
    bound_low = _rate(numerator_low, denominator)
    bound_high = _rate(numerator_high, denominator)

    # ── контроль СПОСОБНОСТИ разойтись ───────────────────────────────────────
    doc["widening_capability"] = _widening_control(
        records, base_rows=base_rows, baseline=baseline, polled=polled, twins=twins,
        points=points, expected=expected, denominator=denominator, horizon=horizon,
        lifted=lifted)
    if not doc["widening_capability"].get("passed"):
        return refuse(
            f"прибор не умеет расходиться границами: {doc['widening_capability'].get('reason')} "
            f"— ширина {0 if bound_low == bound_high else 'ненулевая'} ничего не "
            f"доказывает, пока не показано, ЧТО её раздвигает")

    # ── ответ ────────────────────────────────────────────────────────────────
    threshold = _ste.MIN_HIT_RATE
    passes_low = bound_low is not None and bound_low >= threshold
    passes_high = bound_high is not None and bound_high >= threshold
    doc["answer"] = {
        "denominator": denominator,
        "denominator_today": len(baseline),
        "numerator_low": numerator_low,
        "numerator_high": numerator_high,
        "bound_low": bound_low,
        "bound_high": bound_high,
        "interval_width": (None if bound_low is None or bound_high is None
                           else round(bound_high - bound_low, RATE_DIGITS)),
        "days_resolved_by_material": resolved,
        "days_resolved_outcomes": {d: granted_rows[d].get("outcome") for d in resolved},
        "days_unresolved": unresolved,
        "hit_rate_today": canon_rate,
        # Поля «середина» / «точечная оценка» здесь НЕТ и не будет: заказ запретил её
        # прямо, и запрет держится тестом. Имя поля названо ради читателя, который
        # пойдёт её искать.
        "midpoint": None,
        "midpoint_note": ("НЕ СЧИТАЕТСЯ НАМЕРЕННО: любое число между границами "
                          "означало бы, что про неразрешённый день что-то известно "
                          "(ADR-300). Ответ — пара границ, и обе измерены"),
    }
    doc["gate"] = {
        "min_hit_rate": threshold,
        "passes_at_low_bound": passes_low,
        "passes_at_high_bound": passes_high,
        "verdict_insensitive": passes_low == passes_high,
        "what_it_proves": ("ОТДАЧА починки — меняется ли от неё РЕШЕНИЕ, а не насколько "
                           "сдвинется число. Совпавшие вердикты на обеих границах "
                           "означают, что ценность починки лежит в покрытии населения"),
    }

    # Все контроли пройдены ⇒ замер состоялся. Оставить здесь стартовый UNMEASURED
    # значило бы напечатать измеренный интервал под шапкой «не измерено», и читатель
    # получил бы два ответа об одном прогоне, оба на вид измеренных.
    doc["status"] = STATUS_OK

    f.append(
        f"[ОТВЕТ] значение критерия `hit_rate` на знаменателе {denominator} лежит в "
        f"[{bound_low}, {bound_high}] — обе границы ИЗМЕРЕНЫ, между ними числа нет "
        f"ни одного: разрешено материалом {len(resolved)} дн. из "
        f"{len(expected)} ({', '.join(resolved) or '—'}), не разрешено "
        f"{len(unresolved)} ({', '.join(unresolved) or '—'})")
    f.append(
        f"[БЕЗ СЕНТИНЕЛА] вердикты поднятых дней получены НАСТОЯЩИМИ ставками из ряда "
        f"фидов ({len(provenance)} выданных ставок, каждая найдена обратным чтением) — "
        f"поэтому запрет ADR-300 на печать вердикта здесь не действует, а семь "
        f"предыдущих заказов печатать значение не имели права")
    for day in resolved:
        f.append(f"[ПО ДНЯМ] {day}: {granted_rows[day].get('outcome')} · вердикт "
                 f"{granted_rows[day].get('verdict')} · ставки наблюдены, не подставлены")

    if flipped:
        doc["status"] = STATUS_WARNING
        f.append(
            f"[ЧУВСТВИТЕЛЬНОСТЬ] материал сдвинул исход {len(flipped)} УЖЕ оценённых "
            f"дн. ({', '.join(flipped)}): числитель границ посчитан в возмущённом мире "
            f"целиком, и сегодняшние {len(base_hits)} попаданий стали "
            f"{len(granted_base_hits)}")
    else:
        f.append(
            f"[ОПОРА] материал НЕ сдвинул исход ни одного из {len(baseline)} уже "
            f"оценённых дней — числитель границ опирается на те же попадания, что "
            f"опубликованный `hit_rate` = {canon_rate}. Это измеренный ноль, а не "
            f"пропущенная проверка")

    if bound_low == bound_high:
        f.append(
            f"[ШИРИНА] интервал ВЫРОЖДЕН в точку, и это ИЗМЕРЕННЫЙ исход: материал "
            f"разрешил все {len(expected)} дн., неразрешённых не осталось ни одного. "
            f"Способность прибора расходиться показана отдельно — изъятие материала у "
            f"ног {doc['widening_capability'].get('legs_withheld')} даёт ширину "
            f"{doc['widening_capability'].get('width')}")

    if doc["gate"]["verdict_insensitive"]:
        f.append(
            f"[ОТДАЧА] решение о взводе к этой починке НЕЧУВСТВИТЕЛЬНО: порог "
            f"`MIN_HIT_RATE` = {threshold} пройден на ОБЕИХ границах "
            f"({bound_low} и {bound_high}). Вся отдача ряда G6→G13 по этому критерию "
            f"лежит в ПОКРЫТИИ населения ({len(baseline)} → {denominator} дн.), а не в "
            f"значении — читатель, ставивший починку в очередь ради значения, брал не "
            f"ту единицу")
    else:
        doc["status"] = STATUS_CRITICAL
        f.append(
            f"[CRITICAL] починка способна ПЕРЕВЕРНУТЬ взвод: на нижней границе "
            f"{bound_low} порог {threshold} "
            f"{'пройден' if passes_low else 'НЕ пройден'}, на верхней {bound_high} — "
            f"{'пройден' if passes_high else 'НЕ пройден'}. Место такой починки в "
            f"очереди — первое, и выбор остаётся за владельцем")
    return doc


def _widening_control(records: Dict[str, dict], *, base_rows: Dict[str, dict],
                      baseline: Set[str], polled: Set[str],
                      twins: Dict[str, List[str]],
                      points: Dict[str, Dict[str, float]], expected: Set[str],
                      denominator: int, horizon: int, lifted: Set[str]) -> dict:
    """Тот же расчёт с ИЗЪЯТЫМ материалом у ног одного дня — ширина обязана вырасти.

    Без него нулевая ширина есть вакуум: неотличимо «материал разрешил все дни» от
    «прибор не расходится никогда». Изымаются не выдуманные ключи, а ноги, которыми
    судья и отверг тот день, — они названы в его же строке (``unpriced_protocols``).
    """
    out: dict = {"passed": False, "reason": None}
    if not lifted:
        # Ни одного поднятого дня ⇒ показывать нечего, и это не отказ прибора: он
        # обязан отчитаться об этом, а не выдать несработавший контроль за пройденный.
        out.update({"required": False, "passed": True,
                    "reason": "поднятых дней нет — раздвигать нечего",
                    "legs_withheld": [], "width": None})
        return out
    victim = sorted(lifted)[0]
    legs = observed(base_rows.get(victim) or {}, "unpriced_protocols", kind=list)
    if legs is None:
        out["reason"] = (f"строка судьи за {victim} не несёт списка отвергающих ног — "
                         f"изымать нечего, и «контроль не гонялся» не есть «прошёл»")
        return out
    withhold = sorted({str(x) for x in legs})
    if not withhold:
        out["reason"] = f"список отвергающих ног за {victim} пуст — изымать нечего"
        return out
    starved, _prov = grant_material(records, polled=polled, twins=twins, points=points,
                                    withhold=withhold)
    rows, den = _outcomes(starved, horizon)
    if victim in den:
        out.update({"required": True, "legs_withheld": withhold, "width": 0.0,
                    "reason": (f"изъятие материала у ног {withhold} не помешало дню "
                               f"{victim} подняться — значит поднимался он не "
                               f"материалом, и что раздвигает границы, неизвестно")})
        return out
    unresolved = (expected - (den - baseline))
    hits = len(_hits(rows, den))
    low = _rate(hits, denominator)
    high = _rate(hits + len(unresolved), denominator)
    width = None if low is None or high is None else round(high - low, RATE_DIGITS)
    out.update({
        "required": True,
        "day_starved": victim,
        "legs_withheld": withhold,
        "bound_low": low,
        "bound_high": high,
        "width": width,
        "passed": bool(width and width > 0),
        "what_it_proves": ("прибор РАЗДВИГАЕТ границы, когда день остаётся "
                           "неразрешённым; без этого нулевая ширина на живых данных "
                           "была бы вакуумом, а не ответом"),
    })
    if not out["passed"]:
        out["reason"] = (f"с изъятым материалом у ног {withhold} день {victim} не "
                         f"поднялся, а границы всё равно совпали — прибор не расходится")
    return out


# ── отрисовка для шага 0-офис ────────────────────────────────────────────────
def format_report(doc: dict) -> List[str]:
    """Порядок строк — порядок вопроса: обе границы → чем разрешён каждый день → контроли.

    Границы печатаются ОДНОЙ строкой и всегда вдвоём: разнеси их по строкам, и читатель
    унесёт ту, которая ближе к началу, — то есть снова одно число вместо интервала.
    """
    out: List[str] = []
    ans = doc.get("answer") or {}
    out.append(f"   значение критерия hit_rate ДВУМЯ границами (заказ #600/G14): "
               f"{doc.get('status')} · знаменатель {ans.get('denominator')} "
               f"(сегодня {ans.get('denominator_today')})")
    if doc.get("unmeasured_reason"):
        out.append(f"   [НЕ ИЗМЕРЕНО] {doc['unmeasured_reason']}")
    if ans.get("bound_low") is not None:
        out.append(f"   [ИНТЕРВАЛ] [{ans.get('bound_low')}, {ans.get('bound_high')}] "
                   f"· ширина {ans.get('interval_width')} · числитель от "
                   f"{ans.get('numerator_low')} до {ans.get('numerator_high')} "
                   f"· середины НЕТ намеренно")
    gate = doc.get("gate") or {}
    if gate:
        out.append(f"   порог MIN_HIT_RATE {gate.get('min_hit_rate')}: нижняя граница "
                   f"{'проходит' if gate.get('passes_at_low_bound') else 'НЕ проходит'}"
                   f" · верхняя "
                   f"{'проходит' if gate.get('passes_at_high_bound') else 'НЕ проходит'}"
                   f" ⇒ решение "
                   f"{'НЕЧУВСТВИТЕЛЬНО' if gate.get('verdict_insensitive') else 'МОЖЕТ ПЕРЕВЕРНУТЬСЯ'}")
    for block, label in (("unit_parity", "шкала журнала и ряда"),
                         ("numerator_parity", "сверка числителя с каноническим"),
                         ("ladder_parity", "односторонняя сверка знаменателя с лестницей"),
                         ("provenance_control", "каждая ставка найдена в ряду"),
                         ("widening_capability", "способность разойтись границами")):
        b = doc.get(block) or {}
        if not b:
            continue
        out.append(f"   {label}: " + ("сошлась" if b.get("passed") else "НЕ СОШЛАСЬ"))
    for line in doc.get("findings") or []:
        out.append(f"   {line}")
    note = (doc.get("answer") or {}).get("midpoint_note")
    if note:
        out.append(f"   НЕ ДОКЛАДЫВАЕТ: {note}")
    if doc.get("advisory"):
        out.append(f"   {doc['advisory']}")
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
        "warn": sum(1 for x in findings if x.startswith("[ЧУВСТВИТЕЛЬНОСТЬ]")),
        "info": sum(1 for x in findings
                    if x.startswith(("[ОТВЕТ]", "[БЕЗ СЕНТИНЕЛА]", "[ПО ДНЯМ]",
                                     "[ОПОРА]", "[ШИРИНА]", "[ОТДАЧА]"))),
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
        description="значение критерия hit_rate на знаменателе ступени our_code_floor "
                    "— двумя границами (заказ #600/G14)")
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
