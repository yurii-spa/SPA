"""§49 ТЗ «Portfolio CIO», критерий **Persistence** — входил ли капитал на
ставку, которая к следующей неделе испарилась.

Требование владельца дословно (§49 «Acceptance criteria» карточки
`inbox-task-portfolio-cio-dynamic-capital-alloc`):

    Persistence
    Transient APY spikes не вызывают ненужные trades.

Цикл #700 сверился с §49 целиком и назвал восемь критериев, у которых нет ни
одного замера; этот модуль закрывает ОДИН из них — и закрывает по ИСХОДУ, а не
по устройству: не «умеет ли оптимизатор сглаживать», а **сколько денег уже
вошло на всплеск, которого через неделю не было**.

## Чем это НЕ является — сосед по вопросу назван заранее

`target_stability` (#534, ADR-271) измерил МЕХАНИЗМ: наименьший сдвиг ставки,
переставляющий цель (`маржа`), против собственного дневного хода этой ставки.
Его ответ — «форма оптимизатора усиливает шум входа до хода размером с
потолок», то есть система ПОДВЕРЖЕНА спайкам. Здесь мерится другое и другими
данными: что фактически стало с деньгами, которые уже переложены. Одно
предсказывает уязвимость, другое считает её цену; ни одно не является поправкой
к другому, и совпадение вывода — не двойной счёт, а подтверждение с другой
стороны.

`apy_forecast_accuracy` (#504) мерил ОШИБКУ ПРОГНОЗА ставки. Прогноз может быть
точен, а вход всё равно сделан на всплеске: «ошибся ли прогноз» и «выжил ли
повод» — разные вопросы.

## Как меряется

Население — события `trade_executed` журнала решений (`data/audit_trail.jsonl`).
У каждого хода берутся ВОШЕДШИЕ ноги: ключи, чья сумма выросла между
`from_allocation` и `to_allocation`. Ставки — дневной ряд
`data/apy_series_daily.json` (тот же ряд, по которому мерит
`writer_universe_lever_floor`; ввозить ряд у соседа нельзя — у него своё окно
вопроса, поэтому читается сам артефакт).

У каждой ноги три величины и ни одна не берётся из головы:

* `rate_on_day` — ставка ключа в день входа;
* `base_pre` — МЕДИАНА своих же ``PRE_DAYS`` дней до входа (медиана, а не
  среднее: одиночный выброс в базе испортил бы саму базу);
* `base_fwd` — медиана ``FWD_DAYS`` дней после входа.

**Спайк** — `rate_on_day` выше своей базы и относительно (``SPIKE_REL``), и
абсолютно (``SPIKE_ABS_PP``). Два условия, а не одно: на ставке 0,2 % рост в
1,15 раза — это 0,03 pp, шум округления фида, а не повод переложить капитал.

**Испарился** — `base_fwd` откатилась ниже, чем на ``REVERT_FRAC`` всплеска.

## Порог не решает ответ, и это ИЗМЕРЕНО, а не заявлено

Число, зависящее от порога, обязано предъявить свою чувствительность, иначе
оно есть свойство порога. Поле ``sensitivity`` перебирает ``SPIKE_REL`` ×
``REVERT_FRAC`` целиком. Замер живого трека 26.09: по ``SPIKE_REL`` ответ не
меняется вовсе (всплески крупные), по ``REVERT_FRAC`` ходит 2…4 ноги и
$42 105,26…$107 105,26. То есть головное число — не артефакт настройки, а
зависимость от одного объявленного параметра, и она названа вслух.

## Что нашёл замер живого трека (26.09, цикл #701, `origin/main` ccdbca6e1)

Вошедших ног 172 на $1 086 902,86. Из них:

======================================  =====  ================
класс                                     ног               $
======================================  =====  ================
`spike_reverted` — **находка**               3       77 105,26
`spike_held`                                 2       70 000,00
`no_spike`                                  35      419 736,84
`unmeasured:date_before_window`            117      459 623,64
`unmeasured:key_absent`                     15       60 437,12
======================================  =====  ================

**Первое число отчёта — не находка, а дыра**: у 117 ног из 172 (68 %,
$459 623,64) ставки в день входа НЕ СУЩЕСТВУЕТ ни в одном артефакте — ряд
начинается 2026-08-06, а ходы трека начинаются 2026-06-12. Критерий владельца
на две трети переложенных денег сегодня НЕ ИЗМЕРИМ, и это отдельный исход, а не
ноль находок (инв. #17). Соседняя дыра того же рода: `data/apy_history.json` —
тот источник, который `decision_audit_trail` спрашивает у 46 ходов про
`market snapshot`, — пуст (`protocol_history: {}`), поэтому вторым прибором
восстановить окно тоже нечем.

**Три найденные ноги (ЗАПУСКОМ, не чтением):**

* 2026-08-24, `aave_v3`, $40 000,00 — вошли на 4,1179 % при своей недельной
  базе 3,2752 %; за следующую неделю медиана 3,2770 %. Весь повод (0,84 pp)
  прожил ОДИН день.
* 2026-08-24, `compound_v3`, $35 000,00 — вошли на 6,7125 % при базе 3,5947 %;
  вперёд 5,0469 % (откат больше половины).
* 2026-08-31, `compound_v3`, $2 105,26 — вошли на 7,7122 % при базе 5,0469 %;
  вперёд 4,2041 %.

**И главное про слово «ненужные».** Испарившаяся часть повода стоит в неделю
$6,45 / $11,18 / $1,42 (`promise_gap_usd`), а один только слиппедж входа по
собственной модели издержек системы — $32,00 / $28,00 / $1,68
(``SLIPPAGE_BPS_STABLE`` = 8 bps оборота, ввозится из
`spa_core/backtesting/tier1/cost_model.py`, а не перепечатывается). На ВСЕХ
трёх ногах пошлина за ход больше того всплеска, за которым ход шёл: **спайк не
мог оплатить перекладку, которой он сопутствовал.** Это НЕ значит, что ход был
убыточен — уровень ставки мог оправдывать его и без всплеска, и такого
утверждения прибор не делает (см. ``what_it_does_not_prove``).

Газ в стоимость НЕ входит: сети ноги нет ни в журнале ходов, ни в снимке
оркестратора, а подставить её по имени протокола значило бы выдать литерал за
наблюдение (запрет ADR-053 в его общей форме). Поэтому `cost_usd` объявлен
НИЖНЕЙ границей, и сравнение выше держится именно на ней.

ADVISORY. Модуль только читает. Ни один порог RiskPolicy, ни стоп-кран, ни
живой трек, ни `POLLED_ADAPTERS`, ни сам оптимизатор не трогаются: сглаживать
вход аллокатора — money-path и решение владельца.
"""

# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # pragma: no cover - проводка запуска файлом
    sys.path.insert(0, str(_ROOT))

from spa_core.backtesting.tier1.cost_model import SLIPPAGE_BPS_STABLE  # noqa: E402,E501
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT = "cio_apy_persistence.json"
PRODUCER = "spa_core/monitoring/cio_apy_persistence.py"
SCHEMA = "cio_apy_persistence/v1"

TRAIL_REL = "data/audit_trail.jsonl"
SERIES_REL = "data/apy_series_daily.json"

#: Событие журнала, означающее СОСТОЯВШИЙСЯ ход книги. Предложение
#: (`allocation_proposal`) в население не входит: предложение, не доехавшее до
#: книги, денег не двигало, и считать его «входом на спайке» значило бы
#: предъявить владельцу оборот, которого не было.
EVENT_EXECUTED = "trade_executed"

#: Окно базы и окно проверки — РАВНЫЕ по построению: «до» и «после» обязаны
#: быть одной длины, иначе откат мерился бы другой линейкой, чем повод.
PRE_DAYS = 7
FWD_DAYS = 7
#: Минимум точек, при котором медиана вообще является медианой. Меньше ⇒
#: третий исход, а не медиана из одного наблюдения.
MIN_PRE = 3
MIN_FWD = 3

#: Спайк объявлен ДВУМЯ условиями сразу. Относительное одно даёт ложные
#: находки на малых ставках (1,15 от 0,2 % — это 0,03 pp, шум фида);
#: абсолютное одно — на больших (0,3 pp от 30 % не всплеск, а дрожь).
SPIKE_REL = 1.15
SPIKE_ABS_PP = 0.30
#: Доля всплеска, откат ниже которой считается его исчезновением.
REVERT_FRAC = 0.50

#: Порог существенности ноги. Ход на $12 не является решением о капитале, и
#: считать его входом значило бы утопить находку в округлениях книги. Число
#: взято равным порогу существенности судьи хода (`MATERIAL_TURNOVER_USD`) —
#: одна величина, один смысл; исключённые ноги НАЗЫВАЮТСЯ, а не выбрасываются.
MATERIAL_ENTRY_USD = 100.0

VERDICT_REVERTED = "spike_reverted"
VERDICT_HELD = "spike_held"
VERDICT_NO_SPIKE = "no_spike"
UNMEASURED_KEY_ABSENT = "unmeasured:key_absent"
UNMEASURED_BEFORE = "unmeasured:date_before_window"
UNMEASURED_AFTER = "unmeasured:date_after_window"
UNMEASURED_DAY_GAP = "unmeasured:day_gap"
UNMEASURED_SHORT_PRE = "unmeasured:short_history"
UNMEASURED_SHORT_FWD = "unmeasured:short_forward"
BELOW_MATERIAL = "below_material"

VERDICTS = (VERDICT_REVERTED, VERDICT_HELD, VERDICT_NO_SPIKE,
            UNMEASURED_KEY_ABSENT, UNMEASURED_BEFORE, UNMEASURED_AFTER,
            UNMEASURED_DAY_GAP, UNMEASURED_SHORT_PRE, UNMEASURED_SHORT_FWD,
            BELOW_MATERIAL)
#: Вердикты, при которых наблюдения НЕ БЫЛО. Их нельзя ни складывать с
#: `no_spike` (там наблюдение есть и оно говорит «повода не было»), ни
#: молчаливо считать чистыми.
UNMEASURED_VERDICTS = (UNMEASURED_KEY_ABSENT, UNMEASURED_BEFORE,
                       UNMEASURED_AFTER, UNMEASURED_DAY_GAP,
                       UNMEASURED_SHORT_PRE, UNMEASURED_SHORT_FWD)

#: Сетка чувствительности: ответ обязан предъявить, от какого параметра он
#: зависит, — иначе головное число есть свойство порога, а не трека.
SENSITIVITY_REL = (1.10, 1.15, 1.25)
SENSITIVITY_REVERT = (0.30, 0.50, 0.70)


class NotMeasured(RuntimeError):
    """Материал не прочитан — третий исход, а не пустая перепись."""


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ─── чтение материала ────────────────────────────────────────────────────────

def load_trail(root: Path) -> List[dict]:
    """События журнала решений. Нет файла / не разобран / нет ходов ⇒ отказ."""
    path = root / TRAIL_REL
    if not path.is_file():
        raise NotMeasured(f"{TRAIL_REL} не найден — население ходов не прочитано")
    events: List[dict] = []
    bad = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotMeasured(f"{TRAIL_REL} не прочитан ({exc})") from exc
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:  # noqa: BLE001 — битая строка считается, а не глотается
            bad += 1
            continue
        if isinstance(row, dict):
            events.append(row)
    executed = [e for e in events if e.get("event_type") == EVENT_EXECUTED]
    if not executed:
        raise NotMeasured(
            f"в {TRAIL_REL} нет ни одного события `{EVENT_EXECUTED}` "
            f"(строк {len(events)}, не разобрано {bad}) — мерить нечего")
    return executed


def load_series(root: Path) -> dict[str, dict[str, float]]:
    """Дневной ряд ставок. Пустой ряд — тоже отказ, а не ноль находок."""
    path = root / SERIES_REL
    if not path.is_file():
        raise NotMeasured(f"{SERIES_REL} не найден — ставок в день входа нет")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"{SERIES_REL} не разобран ({exc})") from exc
    raw = (doc or {}).get("series")
    if not isinstance(raw, dict) or not raw:
        raise NotMeasured(f"в {SERIES_REL} нет непустого `series` — ряда ставок нет")
    out: dict[str, dict[str, float]] = {}
    for key, points in raw.items():
        if not isinstance(points, list):
            continue
        per_day: dict[str, float] = {}
        for point in points:
            if isinstance(point, (list, tuple)) and len(point) == 2:
                day, value = point
                try:
                    per_day[str(day)] = float(value)
                except (TypeError, ValueError):
                    continue
        if per_day:
            out[str(key)] = per_day
    if not out:
        raise NotMeasured(f"в {SERIES_REL} ни одна строка ряда не разобрана")
    return out


def series_window(series: dict[str, dict[str, float]]) -> tuple[str, str]:
    days = [d for per_day in series.values() for d in per_day]
    return min(days), max(days)


# ─── население: вошедшие ноги ────────────────────────────────────────────────

def entered_legs(executed: Iterable[dict]) -> List[dict]:
    """Ноги, чья сумма ВЫРОСЛА. Выход (уменьшение) — не предмет этого критерия."""
    legs: List[dict] = []
    for event in executed:
        data = event.get("data") or {}
        before = data.get("from_allocation") or {}
        after = data.get("to_allocation") or {}
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        day = str(event.get("timestamp") or "")[:10]
        for key in sorted(set(before) | set(after)):
            try:
                delta = round(float(after.get(key, 0.0))
                              - float(before.get(key, 0.0)), 2)
            except (TypeError, ValueError):
                continue
            if delta <= 0:
                continue
            legs.append({"date": day, "trade_id": data.get("trade_id"),
                         "protocol": key, "entered_usd": delta})
    return legs


# ─── вердикт одной ноги ──────────────────────────────────────────────────────

def classify_leg(leg: dict, series: dict[str, dict[str, float]],
                 window: tuple[str, str], *,
                 spike_rel: Optional[float] = None,
                 spike_abs_pp: Optional[float] = None,
                 revert_frac: Optional[float] = None) -> dict:
    """Вердикт по одной вошедшей ноге. Пороги — ВХОД, а не окружение.

    Умолчание разрешается ВНУТРИ, а не в подписи. Значение по умолчанию в
    подписи вычисляется один раз при определении функции — то есть становится
    ВТОРОЙ копией порога, которая живёт своей жизнью: правка объявленной
    константы её не меняет, и «порог объявлен один раз» перестаёт быть правдой.
    Нашёл это собственный контроль: мутация `SPIKE_REL` не краснела, потому что
    краснеть было нечему. Одно правило — одна копия.
    """
    spike_rel = SPIKE_REL if spike_rel is None else spike_rel
    spike_abs_pp = SPIKE_ABS_PP if spike_abs_pp is None else spike_abs_pp
    revert_frac = REVERT_FRAC if revert_frac is None else revert_frac
    row = dict(leg)
    row.update({"rate_on_day": None, "base_pre": None, "base_fwd": None,
                "pre_points": 0, "fwd_points": 0, "spike_pp": None,
                "promise_gap_usd": None, "cost_usd": None, "why": None})

    if leg["entered_usd"] < MATERIAL_ENTRY_USD:
        row["verdict"] = BELOW_MATERIAL
        row["why"] = (f"${leg['entered_usd']:,.2f} ниже порога существенности "
                      f"${MATERIAL_ENTRY_USD:,.2f} — округление книги, не решение")
        return row

    per_day = series.get(leg["protocol"])
    if per_day is None:
        row["verdict"] = UNMEASURED_KEY_ABSENT
        row["why"] = (f"ключа `{leg['protocol']}` нет в ряду ставок вовсе — "
                      "«ставки не было» и «ключа нет у производителя» это "
                      "РАЗНЫЕ вещи, и вторая здесь")
        return row

    first, last = window
    if leg["date"] < first:
        row["verdict"] = UNMEASURED_BEFORE
        row["why"] = (f"день входа {leg['date']} лежит ДО начала ряда {first} — "
                      "материала не существует ни в одном артефакте")
        return row
    if leg["date"] > last:
        row["verdict"] = UNMEASURED_AFTER
        row["why"] = f"день входа {leg['date']} лежит ПОСЛЕ конца ряда {last}"
        return row

    rate = per_day.get(leg["date"])
    if rate is None:
        row["verdict"] = UNMEASURED_DAY_GAP
        row["why"] = (f"в окне ряда ({first}..{last}) точки за {leg['date']} "
                      f"у `{leg['protocol']}` нет — пропуск внутри окна")
        return row

    anchor = dt.date.fromisoformat(leg["date"])
    pre = [per_day[d] for d in
           ((anchor - dt.timedelta(days=i)).isoformat() for i in range(1, PRE_DAYS + 1))
           if d in per_day]
    fwd = [per_day[d] for d in
           ((anchor + dt.timedelta(days=i)).isoformat() for i in range(1, FWD_DAYS + 1))
           if d in per_day]
    row.update({"rate_on_day": round(rate, 4), "pre_points": len(pre),
                "fwd_points": len(fwd)})
    if len(pre) < MIN_PRE:
        row["verdict"] = UNMEASURED_SHORT_PRE
        row["why"] = (f"до входа {len(pre)} точк(и) при минимуме {MIN_PRE} — "
                      "медианы базы нет, и подставлять одну точку вместо неё нельзя")
        return row
    if len(fwd) < MIN_FWD:
        row["verdict"] = UNMEASURED_SHORT_FWD
        row["why"] = (f"после входа {len(fwd)} точк(и) при минимуме {MIN_FWD} — "
                      "выжил повод или нет, ещё не наблюдено")
        return row

    base_pre = statistics.median(pre)
    base_fwd = statistics.median(fwd)
    row.update({"base_pre": round(base_pre, 4), "base_fwd": round(base_fwd, 4),
                "spike_pp": round(rate - base_pre, 4)})

    if not (rate > base_pre * spike_rel and rate - base_pre > spike_abs_pp):
        row["verdict"] = VERDICT_NO_SPIKE
        row["why"] = (f"ставка дня {rate:.4f} % не выше своей базы {base_pre:.4f} % "
                      f"ни в {spike_rel} раза, ни на {spike_abs_pp} pp — повода-всплеска "
                      "не было, и это НАБЛЮДЕНИЕ, а не его отсутствие")
        return row

    row["cost_usd"] = round(leg["entered_usd"] * SLIPPAGE_BPS_STABLE / 1e4, 2)
    row["promise_gap_usd"] = round(
        leg["entered_usd"] * (rate - base_fwd) / 100.0 * FWD_DAYS / 365.0, 2)

    if base_fwd < rate - revert_frac * (rate - base_pre):
        row["verdict"] = VERDICT_REVERTED
        row["why"] = (f"вошли на {rate:.4f} % при своей базе {base_pre:.4f} %; "
                      f"за следующие {FWD_DAYS} дн. медиана {base_fwd:.4f} % — "
                      f"повод испарился, а пошлина входа (слиппедж, нижняя "
                      f"граница) ${row['cost_usd']:,.2f} против "
                      f"${row['promise_gap_usd']:,.2f} испарившейся выгоды")
    else:
        row["verdict"] = VERDICT_HELD
        row["why"] = (f"всплеск был ({rate:.4f} % против базы {base_pre:.4f} %) и "
                      f"УДЕРЖАЛСЯ: вперёд {base_fwd:.4f} % — находкой не является")
    return row


# ─── свод ────────────────────────────────────────────────────────────────────

def _tally(rows: Iterable[dict]) -> tuple[dict, dict]:
    counts: dict[str, int] = {}
    usd: dict[str, float] = {}
    for row in rows:
        verdict = row["verdict"]
        counts[verdict] = counts.get(verdict, 0) + 1
        usd[verdict] = round(usd.get(verdict, 0.0) + row["entered_usd"], 2)
    return counts, usd


def sensitivity(legs: List[dict], series: dict[str, dict[str, float]],
                window: tuple[str, str]) -> List[dict]:
    """Ответ при каждом сочетании объявленных порогов — целиком, без выборки."""
    grid: List[dict] = []
    for rel in SENSITIVITY_REL:
        for frac in SENSITIVITY_REVERT:
            hits = [classify_leg(leg, series, window, spike_rel=rel,
                                 revert_frac=frac) for leg in legs]
            reverted = [r for r in hits if r["verdict"] == VERDICT_REVERTED]
            grid.append({"spike_rel": rel, "revert_frac": frac,
                         "legs": len(reverted),
                         "usd": round(sum(r["entered_usd"] for r in reverted), 2)})
    return grid


def measure(root: Path, *, now: Optional[dt.datetime] = None) -> dict:
    executed = load_trail(root)
    series = load_series(root)
    window = series_window(series)
    legs = entered_legs(executed)
    if not legs:
        raise NotMeasured(
            f"среди {len(executed)} ход(ов) нет ни одной ноги с ростом суммы — "
            "входов не было, мерить persistence не на чем")
    rows = [classify_leg(leg, series, window) for leg in legs]
    counts, usd = _tally(rows)

    reverted = [r for r in rows if r["verdict"] == VERDICT_REVERTED]
    unmeasured_rows = [r for r in rows if r["verdict"] in UNMEASURED_VERDICTS]
    control = positive_control()
    findings = _findings(rows, counts, usd, window, len(legs))

    if not control["passed"]:
        status = "UNCHECKED"
    elif any(f["severity"] == "critical" for f in findings):
        status = "CRITICAL"
    elif any(f["severity"] == "warn" for f in findings):
        # Порядок ОБЪЯВЛЕН: названная находка не заслоняется названной дырой и
        # наоборот — обе печатаются безусловно в `report`, а вердикт берёт
        # старшую. Дыра, вытеснившая находку из заголовка, читалась бы как
        # «ничего не нашли».
        status = "WARN"
    elif unmeasured_rows:
        status = "UNCHECKED"
    else:
        status = "OK"

    return {
        "schema": SCHEMA,
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": status,
        "question": ("§49 ТЗ CIO, дословно: «Persistence. Transient APY spikes "
                     "не вызывают ненужные trades.»"),
        "window": {"series_first": window[0], "series_last": window[1],
                   "trade_first": min(l["date"] for l in legs),
                   "trade_last": max(l["date"] for l in legs)},
        "population": {
            "executed_moves": len(executed),
            "entered_legs": len(legs),
            "entered_usd": round(sum(l["entered_usd"] for l in legs), 2),
            "rule": ("ноги с РОСТОМ суммы у событий `trade_executed`; "
                     "предложения в население не входят — не доехавшее до книги "
                     "предложение денег не двигало"),
        },
        "counts": counts,
        "usd": usd,
        "reverted": reverted,
        "unmeasured": unmeasured_rows,
        "rows": rows,
        "sensitivity": sensitivity(legs, series, window),
        "cost_model": {
            "slippage_bps": SLIPPAGE_BPS_STABLE,
            "source": "spa_core/backtesting/tier1/cost_model.py",
            "gas": "НЕ ИЗМЕРЕН",
            "gas_why": ("сети ноги нет ни в журнале ходов, ни в снимке "
                        "оркестратора; подставить её по имени протокола значило "
                        "бы выдать литерал за наблюдение"),
            "bound": ("НИЖНЯЯ граница стоимости хода: только слиппедж входящей "
                      "ноги, без газа и без стоимости выхода"),
        },
        "positive_control": control,
        "findings": findings,
        "what_it_does_not_prove": [
            "ПРИЧИНУ входа: журнал пишет `model_used`, но не пишет, какое "
            "число решило ход, — совпадение входа со всплеском причинностью не "
            "является",
            "убыточность хода: уровень ставки мог оправдывать вход и без "
            "всплеска, и прибор такого утверждения не делает",
            "выходы: критерий §49 про входы на всплеске; продал ли кто-то "
            "дёшево — другой вопрос и другой прибор",
            "ходы, которых нет в журнале решений: дыру записи мерит "
            "`book_second_record` (T008, $14 999,88 без записи), и её "
            "население с этим не совпадает",
            "верность самого ряда ставок: провенанс каждой точки — предмет "
            "`capital_observability_census`",
        ],
        "advisory": ("ADVISORY: пороги RiskPolicy, стоп-кран, живой трек, "
                     "POLLED_ADAPTERS и сам оптимизатор НЕ трогаются — "
                     "сглаживать вход аллокатора это money-path и решение "
                     "владельца"),
    }


def _findings(rows: List[dict], counts: dict, usd: dict,
              window: tuple[str, str], legs_total: int) -> List[dict]:
    out: List[dict] = []
    reverted = [r for r in rows if r["verdict"] == VERDICT_REVERTED]
    if reverted:
        cheaper = [r for r in reverted
                   if r["promise_gap_usd"] is not None
                   and r["cost_usd"] is not None
                   and r["promise_gap_usd"] < r["cost_usd"]]
        out.append({
            "severity": "warn",
            "code": "entered_on_reverted_spike",
            "text": (f"{len(reverted)} вход(ов) на "
                     f"${sum(r['entered_usd'] for r in reverted):,.2f} сделаны на "
                     f"ставке-всплеске, которой через {FWD_DAYS} дн. не было: "
                     + "; ".join(f"{r['date']} {r['protocol']} "
                                 f"${r['entered_usd']:,.2f} "
                                 f"({r['rate_on_day']:.4f} % → {r['base_fwd']:.4f} %)"
                                 for r in reverted)
                     + (f". У {len(cheaper)} из {len(reverted)} испарившаяся "
                        "выгода МЕНЬШЕ одного слиппеджа входа — всплеск не мог "
                        "оплатить перекладку, которой сопутствовал"
                        if cheaper else "")),
        })
    for reason in UNMEASURED_VERDICTS:
        if counts.get(reason):
            out.append({
                "severity": "unchecked",
                "code": reason,
                "text": (f"{counts[reason]} из {legs_total} ног "
                         f"(${usd.get(reason, 0.0):,.2f}) — {reason}: "
                         f"{next(r['why'] for r in rows if r['verdict'] == reason)}"),
            })
    if counts.get(BELOW_MATERIAL):
        out.append({
            "severity": "info",
            "code": BELOW_MATERIAL,
            "text": (f"{counts[BELOW_MATERIAL]} ног "
                     f"(${usd.get(BELOW_MATERIAL, 0.0):,.2f}) ниже порога "
                     f"существенности ${MATERIAL_ENTRY_USD:,.2f} — исключены и "
                     "названы, а не выброшены молча"),
        })
    return out


# ─── положительный контроль ──────────────────────────────────────────────────

def _scene(anchor: dt.date, key: str, pre: float, day: float, post: float,
           *, gap: bool = False) -> dict[str, dict[str, float]]:
    """Синтетический ряд: ``PRE_DAYS`` дней базы, день входа, ``FWD_DAYS`` после."""
    per_day: dict[str, float] = {}
    for i in range(1, PRE_DAYS + 1):
        per_day[(anchor - dt.timedelta(days=i)).isoformat()] = pre
    if not gap:
        per_day[anchor.isoformat()] = day
    for i in range(1, FWD_DAYS + 1):
        per_day[(anchor + dt.timedelta(days=i)).isoformat()] = post
    return {key: per_day}


def positive_control(anchor: Optional[dt.date] = None) -> dict:
    """Зелёный на целом контуре, красный на КАЖДОМ порванном звене.

    Якорь — ВХОД (правило о времени в тестах): сцены строятся от него, поэтому
    в контроле нет ни одной литеральной даты и календарь его не ломает.
    """
    anchor = anchor or (_utcnow().date() - dt.timedelta(days=FWD_DAYS + 1))
    day = anchor.isoformat()
    checks: List[dict] = []

    def verdict(series: dict, key: str = "p", amount: float = 10_000.0) -> str:
        window = series_window(series)
        return classify_leg({"date": day, "trade_id": "TC", "protocol": key,
                             "entered_usd": amount}, series, window)["verdict"]

    checks.append({"name": "всплеск, который испарился — находка",
                   "expected": VERDICT_REVERTED,
                   "got": verdict(_scene(anchor, "p", 3.0, 6.0, 3.0))})
    checks.append({"name": "всплеск, который УДЕРЖАЛСЯ — не находка",
                   "expected": VERDICT_HELD,
                   "got": verdict(_scene(anchor, "p", 3.0, 6.0, 6.0))})
    checks.append({"name": "ровная ставка — наблюдение «повода не было»",
                   "expected": VERDICT_NO_SPIKE,
                   "got": verdict(_scene(anchor, "p", 3.0, 3.0, 3.0))})
    checks.append({"name": "относительный рост без абсолютного не всплеск",
                   "expected": VERDICT_NO_SPIKE,
                   "got": verdict(_scene(anchor, "p", 0.20, 0.26, 0.20))})
    checks.append({"name": "ключа нет в ряду — НЕ ИЗМЕРЕНО, а не «повода не было»",
                   "expected": UNMEASURED_KEY_ABSENT,
                   "got": verdict(_scene(anchor, "other", 3.0, 6.0, 3.0), key="p")})
    checks.append({"name": "пропуск дня внутри окна — НЕ ИЗМЕРЕНО",
                   "expected": UNMEASURED_DAY_GAP,
                   "got": verdict(_scene(anchor, "p", 3.0, 6.0, 3.0, gap=True))})
    # День входа ДО начала ряда: тот же ряд, но нога на PRE_DAYS+1 дней раньше.
    early = _scene(anchor, "p", 3.0, 6.0, 3.0)
    early_window = series_window(early)
    checks.append({
        "name": "день входа до начала ряда — НЕ ИЗМЕРЕНО с названной причиной",
        "expected": UNMEASURED_BEFORE,
        "got": classify_leg(
            {"date": (anchor - dt.timedelta(days=PRE_DAYS + 1)).isoformat(),
             "trade_id": "TC", "protocol": "p", "entered_usd": 10_000.0},
            early, early_window)["verdict"]})
    checks.append({"name": "нога ниже порога существенности исключена С ПРИЧИНОЙ",
                   "expected": BELOW_MATERIAL,
                   "got": verdict(_scene(anchor, "p", 3.0, 6.0, 3.0),
                                  amount=MATERIAL_ENTRY_USD - 1.0)})
    # Выход (уменьшение суммы) входом не является — проверяется на населении.
    exit_only = [{"event_type": EVENT_EXECUTED, "timestamp": f"{day}T00:00:00+00:00",
                  "data": {"trade_id": "TC", "from_allocation": {"p": 20_000.0},
                           "to_allocation": {"p": 5_000.0}}}]
    checks.append({"name": "выход входом не считается",
                   "expected": "0", "got": str(len(entered_legs(exit_only)))})

    for check in checks:
        check["passed"] = check["got"] == check["expected"]
    return {"passed": all(c["passed"] for c in checks), "checks": checks}


# ─── отчёт ───────────────────────────────────────────────────────────────────

def report(doc: dict, *, max_rows: int = 5) -> List[str]:
    out: List[str] = []
    if str(doc.get("status")) == "UNMEASURED":
        out.append(f"НЕ ИЗМЕРЕНО: {doc.get('reason')}")
        return out
    # Инв. #17 у ПЕЧАТИ: `doc.get("counts") or {}` делает «поля нет» и «находок
    # ноль» одной и той же строкой «ИСПАРИЛСЯ 0», и читатель отчёта различить их
    # не может ничем. Поэтому счёт спрашивается честной формой, а его отсутствие
    # печатается словами.
    counts = observed(doc, "counts", kind=dict)
    usd = observed(doc, "usd", kind=dict)
    pop = observed(doc, "population", kind=dict) or {}
    control = observed(doc, "positive_control", kind=dict) or {}
    if counts is None or usd is None:
        out.append("[НЕ ИЗМЕРЕНО] в артефакте нет счёта вердиктов "
                   f"({'counts' if counts is None else ''}"
                   f"{' и ' if counts is None and usd is None else ''}"
                   f"{'usd' if usd is None else ''}) — счёт не печатается, "
                   "и ноль вместо него не подставляется")
        return out
    out.append(
        f"§49 «Persistence» — входы на испарившейся ставке: {doc.get('status')} · "
        f"ног {pop.get('entered_legs')} на ${pop.get('entered_usd', 0.0):,.2f} · "
        f"НА ВСПЛЕСКЕ, КОТОРЫЙ ИСПАРИЛСЯ {counts.get(VERDICT_REVERTED, 0)} = "
        f"${usd.get(VERDICT_REVERTED, 0.0):,.2f}")
    if not control.get("passed"):
        failed = [c.get("name") for c in (control.get("checks") or [])
                  if not c.get("passed")]
        out.append("[НЕ ИЗМЕРЕНО] положительный контроль не пройден "
                   f"({', '.join(filter(None, failed)) or 'причина не названа'}) — "
                   "счёт не читать")
        return out
    unmeasured_legs = sum(counts.get(r, 0) for r in UNMEASURED_VERDICTS)
    unmeasured_usd = sum(usd.get(r, 0.0) for r in UNMEASURED_VERDICTS)
    out.append(f"[НЕ ИЗМЕРЕНО] {unmeasured_legs} из {pop.get('entered_legs')} ног "
               f"(${unmeasured_usd:,.2f}) — ставки в день входа нет; окно ряда "
               f"{(doc.get('window') or {}).get('series_first')}.."
               f"{(doc.get('window') or {}).get('series_last')}, ходы с "
               f"{(doc.get('window') or {}).get('trade_first')}")
    out.append(f"[УДЕРЖАЛСЯ] {counts.get(VERDICT_HELD, 0)} = "
               f"${usd.get(VERDICT_HELD, 0.0):,.2f} · [ПОВОДА НЕ БЫЛО] "
               f"{counts.get(VERDICT_NO_SPIKE, 0)} = "
               f"${usd.get(VERDICT_NO_SPIKE, 0.0):,.2f}")
    for row in (doc.get("reverted") or [])[:max_rows]:
        out.append(f"[ВХОД НА ВСПЛЕСКЕ] {row.get('date')} {row.get('protocol')} "
                   f"${row.get('entered_usd', 0.0):,.2f} — "
                   f"{row.get('rate_on_day')} % при базе {row.get('base_pre')} %, "
                   f"вперёд {row.get('base_fwd')} %; пошлина "
                   f"${row.get('cost_usd', 0.0):,.2f} против испарившейся выгоды "
                   f"${row.get('promise_gap_usd', 0.0):,.2f}")
    grid = doc.get("sensitivity") or []
    if grid:
        span = sorted({(g["legs"], g["usd"]) for g in grid})
        out.append(f"[ПОРОГ НЕ РЕШАЕТ] по всей сетке {len(grid)} сочетаний ответ "
                   f"ходит от {span[0][0]} ног (${span[0][1]:,.2f}) до "
                   f"{span[-1][0]} (${span[-1][1]:,.2f})")
    for finding in (doc.get("findings") or []):
        if finding.get("severity") == "unchecked":
            continue
        out.append(f"[{str(finding.get('severity')).upper()}] {finding.get('text')}"[:600])
    out.append("НЕ ДОКЛАДЫВАЕТ: " + " · ".join(doc.get("what_it_does_not_prove") or []))
    out.append(doc.get("advisory") or "")
    return out


def format_report(doc: dict, *, max_rows: int = 5) -> List[str]:
    """Короткая форма для шага 0-офис."""
    return report(doc, max_rows=max_rows)


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True, now: Optional[dt.datetime] = None) -> dict:
    root = Path(root)
    target = Path(dest) if dest is not None else root / "data" / ARTIFACT
    try:
        doc = measure(root, now=now)
    except NotMeasured as exc:
        doc = {
            "schema": SCHEMA,
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "reason": str(exc),
            "rows": [],
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") != "UNMEASURED", "doc": doc,
            "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="§49 ТЗ CIO «Persistence»: входы на ставке-всплеске, "
                    "которого через неделю не было")
    parser.add_argument("--root", default=str(_ROOT))
    parser.add_argument("--out", default=None)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--max-rows", type=int, default=25)
    args = parser.parse_args(argv)

    outcome = run(Path(args.root), dest=Path(args.out) if args.out else None,
                  write=not args.no_write)
    doc = outcome["doc"]
    for line in report(doc, max_rows=args.max_rows):
        print(line)
    if str(doc.get("status")) == "UNMEASURED":
        return 2
    counts = doc.get("counts")
    # Инв. #17 у кода возврата: «поля нет» и «находок ноль» обязаны различаться,
    # иначе зовущий скрипт прочтёт пустоту как чистый прогон.
    if not isinstance(counts, dict):
        return 2
    return 1 if counts.get(VERDICT_REVERTED, 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
