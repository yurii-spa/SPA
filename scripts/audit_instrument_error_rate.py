#!/usr/bin/env python3
"""
audit_instrument_error_rate.py — какова ЦЕНА ОШИБКИ инструмента, которым мы
собираемся списывать модули?

ЗАЧЕМ ОТДЕЛЬНЫЙ ИНСТРУМЕНТ. `audit_protocol_blindness.py` отвечает «различается
ли score между протоколами». `audit_tier_c_wiring_feasibility.py` отвечает
«можно ли ЧЕСТНО провести модуль на `_protocol_facts`». Оба отвечают про модуль.
Ни один не отвечает про СЕБЯ: сколько раз он ошибается там, где ответ известен.

Без этого числа фраза «второй, более строгий инструмент подтвердил BLIND у 71»
(ADR-190) звучит как независимая улика, хотя сам ADR честно назвал её силу —
«подтверждение на другом ВХОДЕ, не независимый метод». Разница в том, что
величина ошибки НЕ БЫЛА ИЗМЕРЕНА НИ РАЗУ, а решение о списании 71 модуля
принималось так, как если бы она была нулевой.

МЕТОД. Берём популяцию, где ответ известен независимо от проверяемого
инструмента: модули, которые ПЕРВЫЙ инструмент под РЕАЛЬНЫМ входом агрегатора
измеряет как протокол-различающие. Прогоняем по ним ВТОРОЙ инструмент и
считаем, скольким он выносит `BLIND`.

ПОЧЕМУ ЭТО НЕ «ловля второго инструмента на ошибке». Инструменты кормят модуль
РАЗНЫМИ входами: первый — контекстом агрегатора (тем самым, что в проде),
второй — синтетическим `generic_profile_for`. Модуль вправе дать разные числа.
Вывод поэтому не «второй инструмент сломан», а строго следующий:

    вердикт `BLIND` второго инструмента НЕ УСТАНАВЛИВАЕТ, что модуль не читает
    протокол В ПРОДЕ, — и списывать по нему в одиночку нельзя.

ЧИСТОТА ЭТАЛОНА (fail-CLOSED, обе поправки СУЖАЮТ популяцию, не расширяют):
  * `blind_equal_wide_ok` в эталон НЕ ВХОДЯТ. Они равны на тройке ПО
    ПОСТРОЕНИЮ и различают только на широкой вселенной; второй инструмент
    тройку и видит. Считать их ошибкой — подтасовка в свою пользу.
  * `sensitive`, у которых весь разброс — шум float (< `--epsilon`), в эталон
    НЕ ВХОДЯТ: 62.8 против 62.800000000000004 не является чтением протокола.
    Это отдельная находка о ПЕРВОМ инструменте, и она печатается отдельно.

Прогон только в песочнице: тянет прод-модули аналитики.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

#: Тройка, на которой первый инструмент судит о различии. Эталон строится
#: только по ней: второй инструмент видит её целиком (его набор — надмножество).
TRIO = ("aave_v3", "maple", "pendle")

#: Ниже этого разброса «различие» — арифметический шум, а не чтение протокола.
DEFAULT_EPSILON = 1e-6


def trio_spread(entry: Dict[str, Any]) -> Any:
    """Разброс score модуля по тройке. `None`, если сравнивать нечего."""
    runs = entry.get("runs") or {}
    vals = [runs[p].get("score") for p in TRIO
            if isinstance(runs.get(p), dict)]
    real = [v for v in vals if isinstance(v, (int, float))]
    if len(real) < 2:
        # Различие «число против None» — тоже различие, но разброс не определён.
        return "mixed" if (real and len(real) < len(vals)) else None
    return max(real) - min(real)


def build_reference(blindness: List[Dict[str, Any]],
                    epsilon: float) -> Dict[str, List[str]]:
    """Эталон: модули, про которые известно, что они читают протокол."""
    sound, noise, excluded = [], [], []
    for e in blindness:
        cls = e.get("classification")
        if cls != "sensitive":
            if cls == "blind_equal_wide_ok":
                excluded.append(e["module"])
            continue
        sp = trio_spread(e)
        if sp is None:
            excluded.append(e["module"])
        elif sp == "mixed":
            sound.append(e["module"])
        elif sp < epsilon:
            noise.append(e["module"])
        else:
            sound.append(e["module"])
    return {"sound": sound, "float_noise": noise, "excluded": excluded}


def measure(blindness: List[Dict[str, Any]],
            feasibility: List[Dict[str, Any]],
            epsilon: float = DEFAULT_EPSILON) -> Dict[str, Any]:
    ref = build_reference(blindness, epsilon)
    verdicts = {r["module"]: r.get("verdict") for r in feasibility}
    sound = [m for m in ref["sound"] if m in verdicts]
    unseen = [m for m in ref["sound"] if m not in verdicts]
    by_verdict = collections.Counter(verdicts[m] for m in sound)
    false_blind = sorted(m for m in sound if verdicts[m] == "BLIND")
    rate = (len(false_blind) / len(sound)) if sound else None
    return {
        "reference_size": len(sound),
        "reference_not_probed": sorted(unseen),
        "float_noise_in_first_instrument": sorted(ref["float_noise"]),
        "excluded_wide_ok_or_unscorable": len(ref["excluded"]),
        "verdicts_on_reference": dict(by_verdict),
        "false_blind": false_blind,
        "false_blind_rate": rate,
        "epsilon": epsilon,
        "trio": list(TRIO),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--blindness", nargs="+", required=True,
                    help="JSON-отчёты audit_protocol_blindness.py (эталон)")
    ap.add_argument("--feasibility", nargs="+", required=True,
                    help="JSON-отчёты audit_tier_c_wiring_feasibility.py")
    ap.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    ap.add_argument("--out", help="куда положить JSON-отчёт")
    args = ap.parse_args()

    blind: List[Dict[str, Any]] = []
    for p in args.blindness:
        blind.extend(json.load(open(p))["results"])
    feas: List[Dict[str, Any]] = []
    for p in args.feasibility:
        feas.extend(json.load(open(p))["results"])

    rep = measure(blind, feas, args.epsilon)
    if args.out:
        json.dump(rep, open(args.out, "w"), ensure_ascii=False, indent=1)

    n, k = rep["reference_size"], len(rep["false_blind"])
    if n == 0:
        print("НЕЧЕГО МЕРИТЬ: эталон пуст — это находка, а не успех")
        return 2
    print(f"эталон (читают протокол под РЕАЛЬНЫМ входом): {n}")
    print(f"вердикты второго инструмента на эталоне: {rep['verdicts_on_reference']}")
    print(f"ЛОЖНЫЙ BLIND: {k} из {n} = {100 * k / n:.1f}%")
    for m in rep["false_blind"]:
        print(f"   {m}")
    if rep["float_noise_in_first_instrument"]:
        print(f"\nотдельно — ПЕРВЫЙ инструмент считает различием шум float "
              f"({len(rep['float_noise_in_first_instrument'])}): "
              f"{', '.join(rep['float_noise_in_first_instrument'])}")
    if rep["reference_not_probed"]:
        print(f"\nэталонных модулей второй инструмент не прогонял: "
              f"{len(rep['reference_not_probed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
