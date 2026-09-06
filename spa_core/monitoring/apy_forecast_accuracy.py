"""apy_forecast_accuracy.py — насколько ошибается ПРОГНОЗ, которым решается перекладка.

Вопрос владельца, поставленный дословно
=======================================
ТЗ «Portfolio CIO», §49 «Acceptance criteria» → «**Forecast accuracy.** APY
forecast error and break-even error measured». Тело ТЗ ставит тот же вопрос
словами: решение обязано отвечать, «экономически оправдано ли переходить из
текущего allocation в оптимальный прямо сейчас», а «DO NOTHING / KEEP является
полноценным инвестиционным решением».

Ответ на «мерил ли кто-нибудь» — **НЕТ, ни разу**
=================================================
Прогноз записывается каждый цикл и живёт в истории::

    gain_pp      = apy_opt_pp - apy_now_pp     # насколько лучше станет книге
    payback_days = 365 · cost_pp / gain_pp     # когда перекладка окупится

Оба числа — **утверждения о будущем**, и оба решают гейты
``gain_above_band`` (``gain_pp >= required_gain_pp``) и
``payback_within_horizon`` (``payback_days <= max_payback_days``).

Замер дерева: у поля ``gain_pp_claimed`` **ОДИН писатель и НОЛЬ читателей** —
``spa_core/paper_trading/shadow_trigger_eval.py`` его записывает, и больше его
не открывает никто, включая тесты. Тот же класс, что ADR-053 («TVL-floor
проверяется только живым TVL»), ADR-242 («литеральный TVL знаменателем не
является») и ADR-243 («газ наблюдается живьём, а заряжается литералом»):
**измеритель построен, потребителя у него нет.**

При этом сверить прогноз с фактом **можно уже сегодня и без контрфактов**:
накопитель ADR-060 хранит и предложенные ноги (``target_positions`` минус
``current_positions``), и наблюдённые ставки следующих дней
(``apy_evidenced_pct``). Формула дневной выгоды здесь НЕ переписана заново —
переиспользуется ``shadow_trigger_eval._day_gain_usd`` (§3 ТЗ: не строить
вторую модель того же), иначе прогноз и факт разошлись бы по определению
выгоды, а не по существу.

Что показал замер 06.09 — три разных ответа, и ни один не «прогноз точен»
========================================================================

**1. По величине прогноз калиброван.** На днях, где предложение переваливает
полосу гейта (``gain_pp >= required_gain_pp``), отношение «обещано / вышло»
лежит в 0.92…1.30 при медиане ≈ 1.05.

**2. Но худшая ошибка РАВНА зазору, которым решается гейт.** Худшее завышение
измерено ×1.295, а сегодняшний зазор ``max_payback_days / payback_days`` =
30.00 / 23.11 = **×1.298**. То есть ошибка прогноза уже наблюдалась такого
размера, которого достаточно, чтобы перевернуть гейт, решающий о движении
капитала. Ровно то же отношение «ошибка против зазора», которым ADR-243 мерил
стоимость, — и здесь оно едва не единица.

**3. Знак прогноза бывает ПРОТИВОПОЛОЖНЫМ факту.** 2026-08-06 прогноз обещал
+0.523 пп за перекладку $35 000 из ``morpho_steakhouse`` в ``aave_v3``; по
наблюдённым ставкам следующих дней ``morpho_steakhouse`` оказался ЛУЧШЕ на 5
днях из 7, и перекладка принесла бы **минус** $0.17/день. Ошибка не в
величине — в направлении, и направлена она в тот самый ``aave_v3``, о котором
§2 ТЗ говорит «почти 40 % капитала продолжает находиться в Aave V3 под 2.7 %».

Чего мы про этот прогноз сказать НЕ можем — и это главное
=========================================================
Из 32 наблюдённых дней **полностью сверен ровно ОДИН** (полный горизонт, все
ноги с наблюдённой ставкой). Остальные — либо ничего не предлагали (тривиальные
HOLD), либо сверены частично (1–4 дня из 7), либо не сверены вовсе. На
популяции n=1 «прогноз точен» — утверждение, которого замер не выдерживает, и
модуль его не делает: доля полностью сверенных дней печатается рядом с
вердиктом, а не прячется в примечании.

Отдельно проверено и ОПРОВЕРГНУТО естественное объяснение «это просто короткие
окна»: если бы завышение росло от длины окна, оно росло бы и ВНУТРИ одного
вердикта. Замер того же вердикта на растущем окне даёт почти плоское отношение
(2026-08-29: 1.000 → 0.924 за 7 дней; 2026-09-02: 0.986 → 1.019). Значит
разброс — свойство дней, а не горизонта, и списать его на длину окна нельзя.

Чего этот модуль НЕ делает
==========================
**Не чинит прогноз и не трогает гейты.** ``gain_pp``, ``required_gain_pp``,
``max_payback_days``, целевая функция тюнера, RiskPolicy и kill-switch не
изменяются ни одной строкой. Подстроить прогноз — money-path: это изменит
гейт, решающий о движении капитала, и решение владельца, а не агента. Модуль
ADVISORY: он **называет** ошибку, её сторону и её размер относительно зазора.

Ни один порог модулем не назначен
=================================
``required_gain_pp``, ``capital_usd``, ``gain_pp``, ``payback_days`` и
``cost_usd`` читаются из САМОЙ записи вердикта; горизонт окупаемости —
у ``TriggerParams.for_mode()``; горизонт сверки — у ``shadow_trigger_eval``;
формула дневной выгоды — у него же. Литералов решения здесь нет.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/apy_forecast_accuracy.json"

#: Читаем ЖИВОЙ накопитель ADR-060 — тот же файл, в который пишет производитель
#: прогноза. Отдельной копии прогноза не заводим: она разошлась бы молча.
HISTORY_REL = "data/allocation_rationale_history.jsonl"

_UNCHECKED = "UNCHECKED"


def _num(v: object) -> float | None:
    """Число или None. Строку-число принимаем, мусор — нет."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ── Сверка одного вердикта: обещано против вышедшего ──────────────────────────

def score_verdict(rec: dict, forward: list[dict], *, horizon_days: int,
                  day_gain: Callable[[dict, dict], tuple[float | None, list]],
                  deltas_of: Callable[[dict], dict]) -> dict:
    """Один вердикт: прогноз ``gain_pp`` против наблюдённых ставок следующих дней.

    ``day_gain`` и ``deltas_of`` инъектируются НАМЕРЕННО: по умолчанию это
    функции самого производителя прогноза (``shadow_trigger_eval``), и тест
    обязан иметь возможность доказать, что переиспользуется именно они, а не
    похожая формула, написанная здесь заново.
    """
    date = rec.get("cycle_date")
    gain_pp = _num(rec.get("gain_pp"))
    capital = _num(rec.get("capital_usd"))
    band_pp = _num(rec.get("required_gain_pp"))
    out: dict = {
        "cycle_date": date,
        "verdict": str(rec.get("verdict") or "UNKNOWN").upper(),
        "gain_pp_claimed": gain_pp,
        "required_gain_pp": band_pp,
        "capital_usd": capital,
    }

    deltas = deltas_of(rec)
    if not deltas:
        out.update({"scored": False, "reason": "nothing_proposed"})
        return out
    if gain_pp is None or capital is None or capital <= 0.0:
        # Прогноз без своего знаменателя сверять НЕЧЕМ. Подставлять книгу из
        # другого места значило бы сверять обещание одного дня со ставкой другого.
        out.update({"scored": False,
                    "reason": "no_claim" if gain_pp is None else "no_capital"})
        return out

    claimed_usd_per_day = gain_pp / 100.0 * capital / 365.0

    checked = 0
    realised_total = 0.0
    unpriced: set[str] = set()
    for frec in forward[:horizon_days]:
        gain, missing = day_gain(deltas, frec.get("apy_evidenced_pct") or {})
        if gain is None:
            unpriced.update(missing)
            continue
        checked += 1
        realised_total += gain

    out.update({
        "forward_days_checked": checked,
        "forward_days_available": min(len(forward), horizon_days),
        "unpriced_protocols": sorted(unpriced),
    })
    if checked == 0:
        out.update({"scored": False,
                    "reason": ("no_forward_data" if not forward
                               else "no_evidenced_apy_for_moved_legs")})
        return out

    realised_usd_per_day = realised_total / checked
    out.update({
        "scored": True,
        "fully_checked": (checked == horizon_days and not unpriced),
        "claimed_usd_per_day": round(claimed_usd_per_day, 4),
        "realised_usd_per_day": round(realised_usd_per_day, 4),
        # Материальность судит ПОЛОСА САМОГО ГЕЙТА, а не наш литерал: сверять
        # точность на предложениях, которые гейт и так не пропускает, значило бы
        # мерить точность там, где она ни на что не влияет.
        "band_material": bool(band_pp is not None and gain_pp >= band_pp),
        "sign_disagrees": (claimed_usd_per_day > 0.0) != (realised_usd_per_day > 0.0),
    })
    if realised_usd_per_day > 0.0:
        out["ratio_claimed_over_realised"] = round(
            claimed_usd_per_day / realised_usd_per_day, 4)
    return out


def score_window(records: list[dict], *, horizon_days: int,
                 day_gain: Callable[[dict, dict], tuple[float | None, list]],
                 deltas_of: Callable[[dict], dict]) -> list[dict]:
    """Каждый вердикт истории против дней, которые за ним ПОСЛЕДОВАЛИ."""
    out = []
    for i, rec in enumerate(records):
        out.append(score_verdict(rec, records[i + 1:], horizon_days=horizon_days,
                                 day_gain=day_gain, deltas_of=deltas_of))
    return out


# ── Агрегат: величина, направление, и отношение к зазору гейта ────────────────

def magnitude(scores: list[dict]) -> dict:
    """Разброс «обещано / вышло» на днях, которые ГЕЙТ считает существенными."""
    ratios = [s["ratio_claimed_over_realised"] for s in scores
              if s.get("band_material") and s.get("ratio_claimed_over_realised")]
    if not ratios:
        return {"n": 0, "reason": "no band-material day carries a scored ratio"}
    return {
        "n": len(ratios),
        "min": round(min(ratios), 4),
        "median": round(statistics.median(ratios), 4),
        "max": round(max(ratios), 4),
        "worst_overstatement": round(max(ratios), 4),
        "worst_understatement": round(min(ratios), 4),
    }


def direction(scores: list[dict]) -> list[dict]:
    """Дни, где прогноз и факт разошлись ЗНАКОМ — ошибка не величины, а стороны."""
    return [{
        "cycle_date": s.get("cycle_date"),
        "verdict": s.get("verdict"),
        "claimed_usd_per_day": s.get("claimed_usd_per_day"),
        "realised_usd_per_day": s.get("realised_usd_per_day"),
    } for s in scores if s.get("scored") and s.get("sign_disagrees")]


def gate_relation(worst_ratio: float | None, shadow: dict | None,
                  max_payback_days: float | None) -> dict:
    """Ошибка прогноза ПРОТИВ зазора, которым сегодня решается гейт.

    Смысл тот же, что у ADR-243: сама по себе величина ошибки ничего не решает —
    решает её отношение к запасу, с которым проходит (или не проходит) гейт.
    """
    out: dict = {"worst_ratio_observed": worst_ratio}
    if not isinstance(shadow, dict):
        out["reason"] = "no recorded decision to take the margin from"
        return out
    payback = _num(shadow.get("payback_days"))
    gain_pp = _num(shadow.get("gain_pp"))
    band = _num(shadow.get("required_gain_pp"))

    if payback is not None and payback > 0.0 and max_payback_days:
        out["payback_days"] = payback
        out["max_payback_days"] = max_payback_days
        out["payback_margin"] = round(max_payback_days / payback, 4)
    if gain_pp is not None and band:
        out["gain_pp"] = gain_pp
        out["required_gain_pp"] = band
        out["gain_band_margin"] = round(gain_pp / band, 4)

    margins = [m for m in (out.get("payback_margin"), out.get("gain_band_margin"))
               if m is not None]
    if worst_ratio is not None and margins:
        tightest = min(margins)
        out["tightest_gate_margin"] = tightest
        # Завышение прогноза в K раз растягивает срок окупаемости в K раз:
        # payback = 365·cost_pp/gain_pp. Значит ошибка «съедает» зазор, как
        # только K догоняет запас, с которым гейт сегодня проходит.
        out["error_exceeds_margin"] = bool(worst_ratio >= tightest)
        # Порогом находки служит САМ зазор, а не подобранное число, — поэтому
        # severity переключается ровно на пересечении. Но «не пересекло» и
        # «пересекло» — не весь ответ: доля съеденного зазора печатается ВСЕГДА,
        # иначе 99.8 % и 3 % читались бы одинаково спокойно.
        out["margin_consumed_pct"] = round(100.0 * worst_ratio / tightest, 2)
    return out


# ── Прогон ────────────────────────────────────────────────────────────────────

def run(root: str | None = None, *, now: dt.datetime | None = None,
        read: Callable[[str], Any] = _read_json,
        write: bool = True) -> dict:
    """Собрать отчёт. ``now`` инъектируется — иных обращений к часам здесь нет."""
    root = root or REPO_ROOT
    now = now or dt.datetime.now(dt.timezone.utc)

    findings: list[dict] = []
    unchecked: list[str] = []

    # Формула выгоды и разбор ног — у ПРОИЗВОДИТЕЛЯ прогноза, не здесь.
    try:
        from spa_core.paper_trading import shadow_trigger_eval as _ste
        day_gain = _ste._day_gain_usd
        deltas_of = _ste._deltas
        horizon_days = int(_ste.DEFAULT_HORIZON_DAYS)
        load_history = _ste.load_history
        formula_provenance = ("spa_core.paper_trading.shadow_trigger_eval."
                              "_day_gain_usd / _deltas / DEFAULT_HORIZON_DAYS")
    except Exception as exc:  # noqa: BLE001
        # Отсутствие инструмента — САМОСТОЯТЕЛЬНЫЙ третий исход, не ноль и не
        # скип: иначе «нечем мерить» стало бы неотличимо от «ошибки нет».
        return _report(root, now, overall=_UNCHECKED, findings=[],
                       unchecked=[f"формулу выгоды взять неоткуда: {exc}"],
                       population={}, magnitude_={}, direction_=[],
                       gate={}, provenance={}, write=write, read=read)

    try:
        records, bad_lines = load_history(Path(root) / "data")
    except Exception as exc:  # noqa: BLE001
        return _report(root, now, overall=_UNCHECKED, findings=[],
                       unchecked=[f"история вердиктов нечитаема: {exc}"],
                       population={}, magnitude_={}, direction_=[],
                       gate={}, provenance={"formula": formula_provenance},
                       write=write, read=read)

    if not records:
        return _report(root, now, overall=_UNCHECKED, findings=[],
                       unchecked=["история вердиктов пуста — сверять нечего"],
                       population={"days_observed": 0}, magnitude_={},
                       direction_=[], gate={},
                       provenance={"formula": formula_provenance},
                       write=write, read=read)

    scores = score_window(records, horizon_days=horizon_days,
                          day_gain=day_gain, deltas_of=deltas_of)
    scored = [s for s in scores if s.get("scored")]
    population = {
        "days_observed": len(records),
        "scoreable": len(scored),
        "band_material": sum(1 for s in scored if s.get("band_material")),
        "fully_checked": sum(1 for s in scored if s.get("fully_checked")),
        "unparseable_history_lines": bad_lines,
        "horizon_days": horizon_days,
    }

    mag = magnitude(scored)
    signs = direction(scored)

    # Горизонт окупаемости — у своего дома, не литерал.
    max_payback_days = None
    params_provenance = None
    try:
        from spa_core.allocator.rebalance_economics import TriggerParams
        p = TriggerParams.for_mode()
        max_payback_days = float(p.max_payback_days)
        params_provenance = (f"TriggerParams.for_mode() → mode={p.mode} "
                             f"max_payback_days={max_payback_days}")
    except Exception as exc:  # noqa: BLE001
        unchecked.append(f"горизонт окупаемости не прочитан ({exc}) — "
                         f"зазор гейта payback не считается")

    shadow = None
    rat = read(os.path.join(root, "data/allocation_rationale.json"))
    if isinstance(rat, dict):
        shadow = rat.get("decision_shadow")
    if not isinstance(shadow, dict):
        unchecked.append("записанного вердикта нет — зазор гейта не измерен")
    gate = gate_relation(mag.get("worst_overstatement"), shadow, max_payback_days)

    # ── Находки ──────────────────────────────────────────────────────────────
    if signs:
        d = signs[0]
        findings.append({
            "severity": "CRITICAL",
            "code": "forecast_sign_disagrees",
            "message": (
                f"прогноз разошёлся с фактом ЗНАКОМ на {len(signs)} дн. из "
                f"{len(scored)} сверенных; ближайший {d['cycle_date']}: обещано "
                f"{d['claimed_usd_per_day']:+.3f} $/дн., вышло "
                f"{d['realised_usd_per_day']:+.3f} $/дн. — ошибка не в величине, "
                f"а в НАПРАВЛЕНИИ: предложенная перекладка теряла деньги"),
        })
    if gate.get("error_exceeds_margin"):
        findings.append({
            "severity": "CRITICAL",
            "code": "forecast_error_exceeds_gate_margin",
            "message": (
                f"худшее наблюдённое завышение прогноза ×{gate['worst_ratio_observed']} "
                f"при самом узком зазоре гейта ×{gate['tightest_gate_margin']} — "
                f"ошибка ТАКОГО размера уже наблюдалась и её достаточно, чтобы "
                f"перевернуть гейт, решающий о движении капитала"),
        })
    elif gate.get("margin_consumed_pct") is not None:
        findings.append({
            "severity": "INFO",
            "code": "forecast_error_against_gate_margin",
            "message": (
                f"худшее наблюдённое завышение ×{gate['worst_ratio_observed']} "
                f"съедает {gate['margin_consumed_pct']} % зазора гейта "
                f"×{gate['tightest_gate_margin']}, не переходя его"),
        })
    if population["scoreable"] and not population["fully_checked"]:
        findings.append({
            "severity": "WARN",
            "code": "no_fully_checked_day",
            "message": ("ни один сверенный день не сверен ПОЛНОСТЬЮ (полный "
                        "горизонт, все ноги с наблюдённой ставкой) — точность "
                        "прогноза на такой популяции не утверждается"),
        })
    elif population["fully_checked"] and population["fully_checked"] < 5:
        findings.append({
            "severity": "WARN",
            "code": "thin_fully_checked_population",
            "message": (f"полностью сверенных дней {population['fully_checked']} из "
                        f"{population['days_observed']} наблюдённых — популяция "
                        f"слишком мала, чтобы утверждать точность прогноза"),
        })
    if mag.get("n"):
        findings.append({
            "severity": "INFO",
            "code": "magnitude_calibration",
            "message": (f"на {mag['n']} существенных дн. отношение «обещано/вышло» "
                        f"{mag['min']}…{mag['max']} при медиане {mag['median']}"),
        })

    if not scored:
        unchecked.append("ни один вердикт не сверен: предложений не было либо у "
                         "переставляемых ног нет наблюдённой ставки")

    # Вердикт. Третий исход — у АГРЕГАТА: если сверять было нечего, отчёт не
    # имеет права выглядеть как «ошибок не найдено».
    if not scored:
        overall = _UNCHECKED
    elif any(f["severity"] == "CRITICAL" for f in findings):
        overall = "CRITICAL"
    elif any(f["severity"] == "WARN" for f in findings):
        overall = "WARN"
    else:
        overall = "OK"

    return _report(root, now, overall=overall, findings=findings,
                   unchecked=unchecked, population=population, magnitude_=mag,
                   direction_=signs, gate=gate,
                   provenance={"formula": formula_provenance,
                               "params": params_provenance},
                   write=write, read=read)


def _report(root: str, now: dt.datetime, *, overall: str, findings: list[dict],
            unchecked: list[str], population: dict, magnitude_: dict,
            direction_: list[dict], gate: dict, provenance: dict,
            write: bool, read: Callable[[str], Any]) -> dict:
    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "CRITICAL"),
        "warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "info": sum(1 for f in findings if f["severity"] == "INFO"),
        "unchecked": len(unchecked),
    }
    doc = {
        "generated_at": now.isoformat(),
        "overall": overall,
        "counts": counts,
        "population": population,
        "magnitude": magnitude_,
        "sign_disagreements": direction_,
        "gate_relation": gate,
        "provenance": provenance,
        "findings": findings,
        "unchecked": unchecked,
        "advisory": ("ADVISORY: прогноз, гейты и целевая функция НЕ трогаются — "
                     "подстройка прогноза меняет гейт, решающий о движении "
                     "капитала, это money-path и решение владельца"),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, os.path.join(root, REPORT_REL))
    return doc


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, write=not args.no_write)
    print(f"apy_forecast_accuracy: {doc['overall']} "
          f"(critical={doc['counts']['critical']} warn={doc['counts']['warn']} "
          f"info={doc['counts']['info']} unchecked={doc['counts']['unchecked']})")
    for f in doc["findings"]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in doc["unchecked"]:
        print(f"  [НЕ ИЗМЕРЕНО] {u}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
