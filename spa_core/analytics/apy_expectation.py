"""Conservative Expected APY и Persistence/Confidence — §10/§11 приказа владельца.

Предмет — дословный текст ТЗ владельца из якорной карточки
`inbox-task-portfolio-cio-dynamic-capital-alloc`:

    §10 «APY persistence … Система должна определять, насколько вероятно, что
    преимущество сохранится. Первая версия должна быть прозрачной и
    детерминированной. Не использовать opaque ML как обязательный компонент v1.
    Можно использовать: rolling averages; weighted averages; volatility;
    duration above threshold; mean reversion; incentive expiry; utilization
    trend; TVL trend.»

    §11 «Conservative Expected APY … Expected Base APY + Expected Incentive APY
    × Persistence Factor − Uncertainty Haircut … Главное требование: Displayed
    APY != Expected APY.»

До этого цикла §10/§11 не были исполнены ни одним циклом: ADR-953 (§5) объявил
РОДА уже печатаемых чисел, но ни одного числа О БУДУЩЕМ в системе не было вовсе,
а рядом стои́т соседний прибор `monitoring/gain_persistence_census.py` (ADR-508),
который отвечает на ДРУГОЙ вопрос — «сколько дней жило преимущество СОВЕРШЁННОГО
хода», то есть смотрит назад и судит ход, а не возможность.

Главное инженерное решение: НЕИЗМЕРЕННОЕ поднимает HAIRCUT, а не PERSISTENCE
==========================================================================
Из восьми осей, перечисленных владельцем в §10, сегодняшние данные дают пять
(rolling averages, weighted/volatility, duration above threshold, mean reversion,
incentive share) и НЕ дают три (incentive expiry, utilization trend, TVL trend).

Естественное, и НЕВЕРНОЕ, обращение с пробелом — посчитать ненаблюдённую ось
нейтральной, то есть неявно поставить ей «устойчиво». Ошибка пошла бы в опасную
сторону: `Expected = base + reward × P − haircut` растёт с `P`, поэтому слепота
печаталась бы как ОПТИМИЗМ. Поэтому здесь:

* `persistence_factor` считается ТОЛЬКО по измеренным осям и ТОЛЬКО когда
  наблюдений хватает; не хватает ⇒ `None` с названной причиной, а НЕ 1.0;
* каждая слепая ось §10 добавляет к `uncertainty_haircut_pp` объявленную
  надбавку — то есть незнание ВЫЧИТАЕТ из ожидания, а не прибавляет к нему;
* состав ставки (`apy_base`/`apy_reward`) не измерен ⇒ ожидание `None`, а не
  «считаем всю ставку базовой»: вторая форма молча утверждала бы нулевой риск
  истечения стимулов (сегодня таких протоколов 12 из 34).

Ровно тот же урок, что ADR-940/945 («пустой перечень, читаемый только циклом,
есть ЛОЖНОЕ УСИЛЕНИЕ»): два из трёх слепых источников — файлы, которые
СУЩЕСТВУЮТ и ПУСТЫ (`[]`), и прочитанная пустота неотличима от «тревог нет».
Поэтому читатель слепых осей различает «файла нет» · «файл есть и ПУСТ» ·
«данные старше своего срока» · «данные есть, а ПОТРЕБИТЕЛЯ формулы нет» —
и ни одно из этих состояний не является «ось учтена».

Почему «потребителя нет» — отдельное состояние
==============================================
Если бы ось считалась учтённой по факту ПОЯВЛЕНИЯ данных, то в день, когда
кто-нибудь наполнит `tvl_trend_report.json`, haircut упал бы сам, а формула
по-прежнему не читала бы ни одного числа из него: ожидание выросло бы БЕЗ новой
информации. Поэтому ось получает кредит только когда данные измерены И у оси
объявлен потребитель (`consumer`); сегодня у всех трёх его нет, и это
ПЕЧАТАЕТСЯ, а не подразумевается.

Слой — advisory
===============
`IS_ADVISORY = True`. Прибор только ЧИТАЕТ: не правит ни один производитель, не
двигает капитал, не касается RiskPolicy, стоп-крана и аллокатора. Ни одно число
отсюда не является гейтом (инв. 1/9 `CLAUDE.md`). stdlib-only, LLM FORBIDDEN.

Перемер руками::

    python3 -m spa_core.analytics.apy_expectation --data-dir <путь>/data

Коды возврата: 0 — ожидание измерено хотя бы у одной возможности ·
1 — находки (ни одного измеренного ожидания) · 2 — НЕ ИЗМЕРЕНО (вход не прочитан).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ENGINE = "conservative_expected_apy"

#: Слой советательный: ни одно число отсюда не гейтит исполнение (инв. #9).
IS_ADVISORY = True

# ---------------------------------------------------------------------------
# ОБЪЯВЛЕННЫЕ константы формулы. Каждая — выбор, и у каждой названа причина:
# «так получилось» причиной не является (`docs/37`).
# ---------------------------------------------------------------------------

#: Минимум НАБЛЮДЁНИЙ ставки, ниже которого устойчивость не измеряется вовсе.
#: Две недели — наименьшее окно, на котором разброс отличим от одного выброса;
#: меньше ⇒ `None` с причиной, а не «устойчиво».
MIN_OBSERVATIONS = 14

#: Короткое и долгое окна скользящего среднего (в НАБЛЮДЕНИЯХ, не в календарных
#: днях: пропуск дня в ряду означает «фид молчал» и НИКОГДА не интерполируется).
SHORT_WINDOW = 7
LONG_WINDOW = 30

#: Разброс (в процентных пунктах), при котором вклад оси «volatility» обнуляется.
#: Операнд выбран по замеру живого ряда: межпротокольный разброс ставок книги
#: 08.11 — доли пункта, поэтому 2 пп это «ставка гуляет сильнее, чем вся разница
#: между протоколами», то есть уровня у неё нет.
VOL_FULL_PENALTY_PP = 2.0

#: Превышение сегодняшней ставки над СВОИМ ЖЕ долгим средним, при котором вклад
#: оси «mean reversion» обнуляется: +50 % к своему уровню есть спайк, а не уровень.
SPIKE_FULL_PENALTY = 0.50

#: Сколько подряд идущих наблюдений «не ниже своего долгого среднего» даёт полный
#: вклад оси «duration above threshold».
DURATION_FULL_CREDIT = 14

#: Веса осей устойчивости. Сумма ОБЯЗАНА быть 1.0 — это проверяет `validate()`,
#: а не комментарий: иначе `persistence_factor` перестал бы быть долей.
WEIGHT_VOLATILITY = 0.40
WEIGHT_MEAN_REVERSION = 0.40
WEIGHT_DURATION = 0.20

#: Надбавка к haircut: процентные пункты на каждый пункт разброса.
HAIRCUT_VOL_COEF = 0.50

#: Надбавка к haircut за КАЖДУЮ слепую ось §10 (см. шапку: незнание вычитает).
HAIRCUT_PER_BLIND_PP = 0.25

#: Порог старости источника слепой оси. 48 ч — двойной такт дневного цикла.
BLIND_SOURCE_MAX_AGE_H = 48.0

#: Оси §10, для которых сегодня НЕТ ни данных, ни потребителя в формуле.
#: `source` — файл, который НЁС БЫ предмет оси; `None` = такого файла нет вовсе.
#: `consumer` — имя места в формуле, которое число оси читает; `None` = нет.
BLIND_AXES: Tuple[Dict[str, Optional[str]], ...] = (
    {
        "axis": "incentive_expiry",
        "owner_words": "incentive expiry",
        "source": "vault_reward_emission_expiry_cliff_log.json",
        "consumer": None,
        "why": ("срок истечения стимулов не записан ни одним производителем: "
                "`reward_tokens` несёт АДРЕС токена, а не дату обрыва эмиссии"),
    },
    {
        "axis": "utilization_trend",
        "owner_words": "utilization trend",
        "source": None,
        "consumer": None,
        "why": ("фида utilization ПУЛА в data/ нет вовсе; сосед "
                "`borrowing_power_utilization_log.json` — про LTV ЗАЁМЩИКА, "
                "другой предмет, и подставить его значило бы назвать чужое "
                "число своим"),
    },
    {
        "axis": "tvl_trend",
        "owner_words": "TVL trend",
        "source": "tvl_trend_report.json",
        "consumer": None,
        "why": ("снимок TVL есть у каждого адаптера, а РЯДА TVL не пишет никто: "
                "тренд у одной точки не существует"),
    },
)


def validate() -> List[str]:
    """Паритет объявления с собственным контрактом. Пустой список = в порядке.

    Проверяется объявление, а не чьи-то числа: мерка обязана выдерживать свою же
    мерку, иначе сторож сверяет свои константы САМ С СОБОЙ (урок ADR-913/940).
    """
    problems: List[str] = []
    w = WEIGHT_VOLATILITY + WEIGHT_MEAN_REVERSION + WEIGHT_DURATION
    if abs(w - 1.0) > 1e-9:
        problems.append(f"веса осей устойчивости дают {w!r}, а не 1.0 — "
                        "persistence_factor тогда не доля")
    if SHORT_WINDOW >= LONG_WINDOW:
        problems.append(f"короткое окно {SHORT_WINDOW} не короче долгого {LONG_WINDOW}")
    if MIN_OBSERVATIONS < SHORT_WINDOW:
        problems.append(f"MIN_OBSERVATIONS={MIN_OBSERVATIONS} меньше короткого "
                        f"окна {SHORT_WINDOW} — среднее стояло бы на неполном окне")
    for v, name in ((VOL_FULL_PENALTY_PP, "VOL_FULL_PENALTY_PP"),
                    (SPIKE_FULL_PENALTY, "SPIKE_FULL_PENALTY"),
                    (DURATION_FULL_CREDIT, "DURATION_FULL_CREDIT"),
                    (HAIRCUT_PER_BLIND_PP, "HAIRCUT_PER_BLIND_PP")):
        if not v > 0:
            problems.append(f"{name}={v!r} — порог обнуления обязан быть положительным")
    if HAIRCUT_VOL_COEF < 0:
        problems.append("HAIRCUT_VOL_COEF отрицателен — разброс УМЕНЬШАЛ бы haircut")
    seen = set()
    for ax in BLIND_AXES:
        a = ax.get("axis")
        if not a:
            problems.append("ось §10 без имени объявлением не является")
            continue
        if a in seen:
            problems.append(f"ось {a!r} объявлена дважды")
        seen.add(a)
        if not (ax.get("why") or "").strip():
            problems.append(f"{a}: причина слепоты не названа словами")
        if not (ax.get("owner_words") or "").strip():
            problems.append(f"{a}: не названа формулировка владельца из §10")
    return problems


# ---------------------------------------------------------------------------
# Чтение
# ---------------------------------------------------------------------------

def _num(v: Any) -> Optional[float]:
    """float или None; bool и NaN/inf числами не считаются."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _load(path: Path) -> Tuple[Any, str]:
    """(документ, причина-отказа). Отсутствие и нечитаемость РАЗЛИЧИМЫ."""
    if not path.exists():
        return None, f"{path.name}: файла нет"
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
        return None, f"{path.name}: не разобран ({type(exc).__name__}: {exc})"


def _mtime_age_h(path: Path, now: datetime) -> Optional[float]:
    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except BaseException:  # noqa: BLE001
        return None
    return (now - ts).total_seconds() / 3600.0


def blind_axes_state(data_dir: Path, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Состояние каждой слепой оси §10. ЧЕТЫРЕ исхода, и ни один не «учтена».

    `now` — ВХОД, а не стенные часы (`.claude/rules/deployment.md` § «Время в
    тестах»): иначе проверка срока стала бы будильником.
    """
    now = now or datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for ax in BLIND_AXES:
        rec: Dict[str, Any] = {
            "axis": ax["axis"],
            "owner_words": ax["owner_words"],
            "source": ax["source"],
            "consumer": ax["consumer"],
            "why": ax["why"],
        }
        src = ax["source"]
        if src is None:
            rec["state"] = "blind_no_source"
            rec["detail"] = "файла с предметом этой оси в data/ не существует"
        else:
            p = data_dir / src
            doc, why = _load(p)
            if why:
                rec["state"] = "blind_no_data"
                rec["detail"] = why
            elif isinstance(doc, (list, dict)) and len(doc) == 0:
                # ADR-940: прочитанная ПУСТОТА не есть «находок нет».
                rec["state"] = "blind_empty"
                rec["detail"] = (f"{src}: файл есть и ПУСТ — пустой перечень "
                                 "ответом об оси не является")
            else:
                age = _mtime_age_h(p, now)
                if age is None:
                    rec["state"] = "blind_no_data"
                    rec["detail"] = f"{src}: возраст не измерен"
                elif age > BLIND_SOURCE_MAX_AGE_H:
                    rec["state"] = "blind_stale"
                    rec["detail"] = (f"{src}: данные есть, но им {age:.1f} ч при "
                                     f"пределе {BLIND_SOURCE_MAX_AGE_H:.0f} ч")
                elif ax["consumer"] is None:
                    # Данные пришли, а формула их НЕ ЧИТАЕТ. Если бы кредит
                    # давался за появление данных, haircut упал бы без новой
                    # информации (см. шапку модуля).
                    rec["state"] = "blind_no_consumer"
                    rec["detail"] = (f"{src}: данные измерены, но потребителя в "
                                     "формуле нет — кредит за них не выдаётся")
                else:
                    rec["state"] = "credited"
                    rec["detail"] = f"{src}: измерено и читается ({ax['consumer']})"
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# §10 — устойчивость
# ---------------------------------------------------------------------------

def _stdev(xs: List[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def persistence(points: List[Tuple[str, float]]) -> Dict[str, Any]:
    """Устойчивость ставки ОДНОЙ возможности по наблюдённому ряду.

    `points` — [(дата, ставка %)] по возрастанию даты, БЕЗ интерполяции пропусков.

    Возвращает запись, у которой `factor` либо число 0…1, либо `None` с
    названной причиной в `unmeasured`. Ноль и «не измерено» РАЗЛИЧИМЫ (инв. #17):
    `factor == 0.0` значит «измерено и ставка не держится», `None` — «мерить не на чем».
    """
    rec: Dict[str, Any] = {"observations": len(points)}
    if len(points) < MIN_OBSERVATIONS:
        rec["factor"] = None
        rec["unmeasured"] = (f"наблюдений {len(points)} при минимуме "
                             f"{MIN_OBSERVATIONS} — устойчивость не измеряется")
        return rec

    vals = [v for _, v in points]
    short = vals[-SHORT_WINDOW:]
    long_ = vals[-LONG_WINDOW:]
    cur = vals[-1]
    mean_short = sum(short) / len(short)
    mean_long = sum(long_) / len(long_)
    vol = _stdev(long_)

    rec["current_pct"] = round(cur, 4)
    rec["mean_short_pct"] = round(mean_short, 4)
    rec["mean_long_pct"] = round(mean_long, 4)
    rec["long_window_observations"] = len(long_)
    rec["first_date"] = points[0][0]
    rec["last_date"] = points[-1][0]

    if vol is None:
        rec["factor"] = None
        rec["unmeasured"] = "разброс не измерен: в долгом окне меньше двух наблюдений"
        return rec
    rec["vol_pp"] = round(vol, 4)

    if not mean_long > 0:
        # Спайк определён ОТНОСИТЕЛЬНО уровня; уровня нет ⇒ отказ, а не ноль.
        rec["factor"] = None
        rec["unmeasured"] = (f"долгое среднее {mean_long:.4f} % не положительно — "
                             "«превышение своего уровня» у него не определено")
        return rec

    # ось «duration above threshold»: порог — СВОЁ ЖЕ долгое среднее. Операнд
    # выбран и назван: вопрос «сегодняшний уровень — это уровень или выброс».
    streak = 0
    for v in reversed(long_):
        if v >= mean_long:
            streak += 1
        else:
            break
    rec["observations_at_or_above_mean"] = streak
    rec["threshold_operand"] = "своё долгое среднее"

    vol_term = 1.0 - min(1.0, vol / VOL_FULL_PENALTY_PP)
    excess = max(0.0, (cur - mean_long) / mean_long)
    rec["excess_over_mean_share"] = round(excess, 4)
    spike_term = 1.0 - min(1.0, excess / SPIKE_FULL_PENALTY)
    dur_term = min(1.0, streak / float(DURATION_FULL_CREDIT))

    rec["terms"] = {"volatility": round(vol_term, 4),
                    "mean_reversion": round(spike_term, 4),
                    "duration": round(dur_term, 4)}
    factor = (WEIGHT_VOLATILITY * vol_term
              + WEIGHT_MEAN_REVERSION * spike_term
              + WEIGHT_DURATION * dur_term)
    rec["factor"] = round(max(0.0, min(1.0, factor)), 4)
    return rec


# ---------------------------------------------------------------------------
# §11 — Conservative Expected APY
# ---------------------------------------------------------------------------

def conservative_expected(base_pct: Optional[float], reward_pct: Optional[float],
                          factor: Optional[float], haircut_pp: float,
                          composition_unmeasured: Optional[str] = None,
                          ) -> Tuple[Optional[float], str]:
    """`base + reward × persistence − haircut`, либо `None` с причиной.

    Отказ fail-CLOSED по каждому операнду намеренно: «считаем всю ставку базовой»
    молча утверждало бы нулевой риск истечения стимулов, а «persistence = 1»
    печатало бы слепоту как оптимизм (см. шапку модуля).
    """
    if composition_unmeasured:
        return None, (f"состав ставки НЕ ИЗМЕРЕН ({composition_unmeasured}) — "
                      "принять всю ставку базовой значило бы утверждать нулевой "
                      "риск истечения стимулов")
    if base_pct is None:
        return None, "базовой ставки (`apy_base`) у протокола не записано"
    if reward_pct is None:
        return None, "ставки стимулов (`apy_reward`) у протокола не записано"
    if factor is None:
        return None, "устойчивость не измерена — множителя у стимулов нет"
    value = base_pct + reward_pct * factor - haircut_pp
    return round(max(0.0, value), 4), ""


def measure(data_dir: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Секция цикла: ожидание по каждой возможности + состояние слепых осей."""
    data_dir = Path(data_dir)
    now = now or datetime.now(timezone.utc)

    rep: Dict[str, Any] = {
        "status": "OK",
        "engine": ENGINE,
        "is_advisory": IS_ADVISORY,
        "formula": ("conservative_expected = apy_base + apy_reward × "
                    "persistence_factor − uncertainty_haircut_pp"),
        "declared": {
            "min_observations": MIN_OBSERVATIONS,
            "short_window": SHORT_WINDOW,
            "long_window": LONG_WINDOW,
            "vol_full_penalty_pp": VOL_FULL_PENALTY_PP,
            "spike_full_penalty": SPIKE_FULL_PENALTY,
            "duration_full_credit": DURATION_FULL_CREDIT,
            "weights": {"volatility": WEIGHT_VOLATILITY,
                        "mean_reversion": WEIGHT_MEAN_REVERSION,
                        "duration": WEIGHT_DURATION},
            "haircut_vol_coef": HAIRCUT_VOL_COEF,
            "haircut_per_blind_pp": HAIRCUT_PER_BLIND_PP,
        },
    }

    broken = validate()
    if broken:
        rep["status"] = "SKIPPED"
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = ["объявление формулы не выдерживает своего контракта: "
                             + "; ".join(broken)]
        rep["reason"] = rep["unmeasured"][0]
        return rep

    blind = blind_axes_state(data_dir, now=now)
    rep["blind_axes"] = blind
    n_blind = sum(1 for b in blind if b["state"] != "credited")
    rep["blind_axes_count"] = n_blind
    rep["blind_axes_credited"] = len(blind) - n_blind
    haircut_blind = round(HAIRCUT_PER_BLIND_PP * n_blind, 4)
    rep["haircut_from_blind_axes_pp"] = haircut_blind

    status_doc, why_status = _load(data_dir / "adapter_status.json")
    series_doc, why_series = _load(data_dir / "apy_series_daily.json")
    unmeasured: List[str] = []
    if why_status or not isinstance(status_doc, dict):
        unmeasured.append(why_status or "adapter_status.json не является записью")
    if why_series or not isinstance(series_doc, dict):
        unmeasured.append(why_series or "apy_series_daily.json не является записью")
    if unmeasured:
        rep["status"] = "SKIPPED"
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = unmeasured
        rep["reason"] = "; ".join(unmeasured)
        return rep

    adapters = status_doc.get("adapters")
    series = series_doc.get("series")
    if not isinstance(adapters, dict) or not adapters:
        rep["status"] = "SKIPPED"
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = ["в adapter_status.json нет перечня `adapters` — "
                             "ноль возможностей и непрочитанный вход неразличимы"]
        rep["reason"] = rep["unmeasured"][0]
        return rep
    if not isinstance(series, dict):
        series = {}

    rows: List[Dict[str, Any]] = []
    no_series: List[str] = []
    for aid in sorted(adapters):
        a = adapters[aid]
        if not isinstance(a, dict):
            continue
        raw = series.get(aid)
        points: List[Tuple[str, float]] = []
        if isinstance(raw, list):
            for item in raw:
                if (isinstance(item, (list, tuple)) and len(item) == 2
                        and isinstance(item[0], str)):
                    v = _num(item[1])
                    if v is not None:
                        points.append((item[0], v))
        points.sort(key=lambda p: p[0])
        if not points:
            no_series.append(aid)

        pers = persistence(points)
        vol = pers.get("vol_pp")
        haircut = haircut_blind + (HAIRCUT_VOL_COEF * vol if vol is not None else 0.0)
        haircut = round(haircut, 4)

        displayed = _num(a.get("live_apy"))
        if displayed is None:
            displayed = _num(a.get("apy"))
        base = _num(a.get("apy_base"))
        reward = _num(a.get("apy_reward"))
        comp_unmeasured = a.get("apy_composition_unmeasured")

        expected, why_exp = conservative_expected(
            base, reward, pers.get("factor"), haircut,
            composition_unmeasured=comp_unmeasured if isinstance(comp_unmeasured, str) else None)

        row: Dict[str, Any] = {
            "adapter_id": aid,
            "tier": a.get("tier"),
            "displayed_apy_pct": displayed,
            "base_apy_pct": base,
            "incentive_apy_pct": reward,
            "mean_apy_7d_pct": pers.get("mean_short_pct"),
            "mean_apy_30d_pct": pers.get("mean_long_pct"),
            "apy_vol_30d_pp": vol,
            "observations": pers.get("observations"),
            "observations_at_or_above_mean": pers.get("observations_at_or_above_mean"),
            "persistence_factor": pers.get("factor"),
            "persistence_terms": pers.get("terms"),
            "uncertainty_haircut_pp": haircut if pers.get("factor") is not None else None,
            "conservative_expected_apy_pct": expected,
        }
        if pers.get("unmeasured"):
            row["persistence_unmeasured"] = pers["unmeasured"]
        if why_exp:
            row["expected_unmeasured"] = why_exp
        if expected is not None and displayed is not None:
            row["gap_pp"] = round(displayed - expected, 4)
        rows.append(row)

    rep["opportunities"] = rows
    measured = [r for r in rows if r["conservative_expected_apy_pct"] is not None]
    equal = [r for r in measured if r.get("gap_pp") == 0.0]
    rep["counts"] = {
        "adapters": len(rows),
        "persistence_measured": sum(1 for r in rows if r["persistence_factor"] is not None),
        "persistence_unmeasured": sum(1 for r in rows if r["persistence_factor"] is None),
        "expected_measured": len(measured),
        "expected_unmeasured": len(rows) - len(measured),
        "expected_equals_displayed": len(equal),
        "adapters_without_series": len(no_series),
    }
    rep["adapters_without_series"] = sorted(no_series)
    if measured:
        gaps = [r["gap_pp"] for r in measured if r.get("gap_pp") is not None]
        if gaps:
            rep["gap_pp_min"] = round(min(gaps), 4)
            rep["gap_pp_max"] = round(max(gaps), 4)
            rep["gap_pp_mean"] = round(sum(gaps) / len(gaps), 4)
    else:
        rep["verdict"] = "UNMEASURED"
        rep["unmeasured"] = ["ни одного ожидания не измерено — причины названы "
                             "у каждой возможности поимённо"]
    return rep


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print(rep: Dict[str, Any]) -> int:
    print(f"CONSERVATIVE EXPECTED APY (§10/§11) — {rep.get('status')}"
          f"{'  [ADVISORY]' if rep.get('is_advisory') else ''}")
    if rep.get("verdict") == "UNMEASURED" and not rep.get("opportunities"):
        for u in rep.get("unmeasured") or []:
            print(f"  НЕ ИЗМЕРЕНО: {u}")
        return 2
    c = rep.get("counts") or {}
    print(f"  возможностей {c.get('adapters')} · устойчивость измерена "
          f"{c.get('persistence_measured')} / НЕ ИЗМЕРЕНА {c.get('persistence_unmeasured')}")
    print(f"  ожидание измерено {c.get('expected_measured')} / НЕ ИЗМЕРЕНО "
          f"{c.get('expected_unmeasured')} · равно напечатанному "
          f"{c.get('expected_equals_displayed')}")
    print(f"  слепых осей §10: {rep.get('blind_axes_count')} из "
          f"{len(rep.get('blind_axes') or [])} ⇒ haircut "
          f"{rep.get('haircut_from_blind_axes_pp')} пп")
    for b in rep.get("blind_axes") or []:
        print(f"     [{b['state']}] {b['axis']} ({b['owner_words']}): {b['detail']}")
    if rep.get("gap_pp_mean") is not None:
        print(f"  зазор «напечатано − ожидание»: мин {rep.get('gap_pp_min')} · "
              f"сред {rep.get('gap_pp_mean')} · макс {rep.get('gap_pp_max')} пп")
    for r in rep.get("opportunities") or []:
        if r["conservative_expected_apy_pct"] is None:
            continue
        print(f"     {r['adapter_id']:<22} напечатано {r['displayed_apy_pct']:>7.4f} % → "
              f"ожидание {r['conservative_expected_apy_pct']:>7.4f} % "
              f"(P={r['persistence_factor']}, haircut={r['uncertainty_haircut_pp']} пп)")
    n_unmeas = (rep.get("counts") or {}).get("expected_unmeasured") or 0
    if n_unmeas:
        print(f"  НЕ ИЗМЕРЕНО у {n_unmeas} возможностей — причины:")
        shown = set()
        for r in rep.get("opportunities") or []:
            why = r.get("expected_unmeasured") or r.get("persistence_unmeasured")
            if why and why[:40] not in shown:
                shown.add(why[:40])
                print(f"     · {why}")
    return 0 if (rep.get("counts") or {}).get("expected_measured") else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default="data",
                    help="каталог состояния (живой трек — у ПРОД-дерева)")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    rep = measure(Path(ns.data_dir))
    if ns.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if (rep.get("counts") or {}).get("expected_measured") else (
            2 if rep.get("status") == "SKIPPED" else 1)
    return _print(rep)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
