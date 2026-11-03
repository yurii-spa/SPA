"""TRP-05: эксперимент «дробный размер позиции + полоса ребаланса» по предрегистрированному контракту.

Research-only. Новая модель исполнения ``spot_frac@v1`` живёт здесь и НЕ меняет ``execution.step``: контроль
исполняется действующим ``execution.simulate`` без изменений, а равенство ``spot_frac(k=1, band=None)`` контролю
проверяется на каждом прогоне (иначе сравнение мерило бы разницу двух симуляторов, а не размера).

Попытка списывается из бюджета контракта ДО прогона (``research_contract.spend_attempt``). Данные — только
копия ``market.db`` (открывается на чтение). Ни одна книга, кандидат или ledger не меняется."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import market_data as md
from . import research_contract as rc
from .backtest import code_version, data_ref
from .execution import EXEC_MODELS, simulate
from .metrics import evaluate
from .strategies import by_id

MODEL_ID = "spot_frac@v1"


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


@dataclass
class FracResult:
    equity: List[float]
    weight: List[float]          # доля BTC в капитале на закрытии бара
    position: List[int]          # 1, если BTC держится в баре (для общей метрики exposure)
    cost_paid: float
    turnover: float              # сумма |Δвеса| по всем исполнениям
    rebalances: int
    trades: List[dict]
    bar_cost: List[float]        # издержки, уплаченные в баре i (для срезов периода)
    bar_turn: List[float]        # |Δвеса|, проторгованное в баре i
    bar_rebalance: List[int]


def simulate_frac(bars, targets, *, k: float, band: Optional[float], cost_per_side: float,
                  cost_mult: float = 1.0, equity0: float = 1.0) -> FracResult:
    """Цель бара t (по закрытию t) исполняется на открытии t+1 — тот же контракт против заглядывания."""
    c = cost_per_side * cost_mult
    cash, qty = equity0, 0.0
    res = FracResult([equity0], [0.0], [0], 0.0, 0.0, 0, [], [0.0], [0.0], [0])
    entry_val = None
    for i in range(1, len(bars)):
        b, want = bars[i], targets[i - 1]
        value = cash + qty * b.open
        w = qty * b.open / value if value > 0 else 0.0
        goal, fee, dw, reb = None, 0.0, 0.0, 0
        if want > 0 and qty == 0:
            goal, entry_val = k, value
        elif want <= 0 and qty > 0:
            goal = 0.0
        elif want > 0 and band is not None and abs(w - k) > band:
            goal, reb = k, 1
            res.rebalances += 1
        if goal is not None and value > 0:
            new_qty = goal * value / b.open
            fee = abs(new_qty - qty) * b.open * c
            dw = abs(goal - w)
            res.turnover += dw
            cash = value - new_qty * b.open - fee
            res.cost_paid += fee
            if goal == 0.0 and entry_val:
                res.trades.append({"ret": (cash / entry_val) - 1, "exit_time": b.open_time})
                entry_val = None
            qty = new_qty
        eq = cash + qty * b.close
        res.equity.append(eq)
        res.weight.append(qty * b.close / eq if eq > 0 else 0.0)
        res.position.append(1 if qty > 0 else 0)
        res.bar_cost.append(fee)
        res.bar_turn.append(dw)
        res.bar_rebalance.append(reb)
    return res


def _slice(bars, lo, hi):
    idx = [i for i, b in enumerate(bars) if b.open_time >= lo and (hi is None or b.open_time < hi)]
    return (idx[0], idx[-1]) if len(idx) >= 3 else (None, None)


def _metrics(r, bars, lo, hi, tf, frac: FracResult) -> Dict[str, Any]:
    a, z = _slice(bars, lo, hi)
    if a is None:
        return {"bars": 0, "measured": False}
    eq, pos = r.equity[a:z + 1], r.position[a:z + 1]
    trades = [t for t in r.trades if bars[a].open_time <= t["exit_time"] <= bars[z].open_time]
    m = evaluate(eq, pos, trades, tf)
    m["first_bar"], m["last_bar"] = bars[a].open_time, bars[z].open_time
    m["cash_share_mean"] = 1 - sum(frac.weight[a:z + 1]) / (z - a + 1)
    m["cost_paid"] = sum(frac.bar_cost[a + 1:z + 1])          # издержки баров периода, в единицах капитала 2017 г.
    m["cost_share_of_start_equity"] = m["cost_paid"] / eq[0] if eq[0] > 0 else None   # сравнимо между конфигурациями
    m["turnover_weight_per_year"] = sum(frac.bar_turn[a + 1:z + 1]) / m["years"] if m.get("years") else None
    m["rebalances"] = sum(frac.bar_rebalance[a + 1:z + 1])
    m["funding"] = 0.0                                         # спот: по устройству модели
    return m


def _hold(bars, lo, hi, c, tf) -> Dict[str, Any]:
    a, z = _slice(bars, lo, hi)
    if a is None:
        return {"bars": 0, "measured": False}
    qty = (1 - c) / bars[a].open
    eq = [1.0] + [qty * bars[i].close for i in range(a, z + 1)]
    return {**evaluate(eq, [0] + [1] * (z - a + 1), [], tf), "cost_share_of_start_equity": c, "funding": 0.0,
            "cash_share_mean": 0.0, "turnover_weight_per_year": None, "rebalances": 0}


def run(contract_path: Path, market_db: Path) -> Dict[str, Any]:
    contract = json.loads(Path(contract_path).read_text())
    errs = rc.validate(contract)
    if errs:
        raise ValueError(f"контракт не годен: {errs}")
    per = contract["scope"]["periods"]
    lo_s, hi_s = (x.strip().split(" ")[0] for x in per["oos"].split(".."))
    oos_lo, oos_hi = _ms(lo_s), _ms(hi_s)             # обе границы — из контракта, не из кода
    control_ref = next(x for x in contract["ledger_refs"]["candidates"] if x["role"] == "control")
    cand = by_id()[control_ref["id"]]
    if cand.def_hash != control_ref["def_hash"]:
        raise ValueError("определение контроля изменилось после регистрации — это другой кандидат")
    attempt = rc.spend_attempt(contract_path, {"started_at": datetime.now(timezone.utc).isoformat(),
                                               "code_version": code_version(),
                                               "market_sha256": hashlib.sha256(Path(market_db).read_bytes()).hexdigest()})
    from .read_model import open_ro   # одна дверь read-only (migrate_callsites)
    conn = open_ro(market_db)
    try:
        bars = md.aggregate(md.load_1h(conn, "BTCUSDT"), cand.timeframe)
    finally:
        conn.close()
    targets = cand.signal(bars)
    model = EXEC_MODELS[cand.exec_model]
    cps, tf = model.cost_per_side, cand.timeframe
    out: Dict[str, Any] = {"contract_id": contract["contract_id"], "contract_hash": rc.contract_hash(contract),
                           "attempt": attempt, "attempt_budget": contract["attempt_budget"], "model": MODEL_ID,
                           "code_version": code_version(), "data_ref": data_ref(bars), "bars": len(bars),
                           "data_last_bar": bars[-1].open_time, "oos": [oos_lo, oos_hi], "configs": {}}
    # проверка эквивалентности симуляторов на ВСЕЙ истории — до какого-либо сравнения
    ctrl = simulate(bars, targets, model, tf_ms=md.TF_MS[tf])
    same = simulate_frac(bars, targets, k=1.0, band=None, cost_per_side=cps)
    gap = max(abs(x - y) for x, y in zip(ctrl.equity, same.equity))
    out["equivalence_k1_vs_control_max_abs"] = gap
    if gap > 1e-9:
        raise AssertionError(f"spot_frac(k=1) расходится с контролем на {gap} — сравнение было бы недействительным")
    for cfg in contract["strategy"]["configs"]:
        row: Dict[str, Any] = {"k": cfg["k"], "band": cfg["band"], "role": cfg["role"]}
        for mult in contract["cost_model"]["sensitivity"]:
            k, band = (1.0, None) if cfg["role"] == "control" else (cfg["k"], cfg["band"])
            f = simulate_frac(bars, targets, k=k, band=band, cost_per_side=cps, cost_mult=mult)
            r = simulate(bars, targets, model, tf_ms=md.TF_MS[tf], cost_mult=mult) if cfg["role"] == "control" else f
            row[f"{mult:g}x"] = {"oos": _metrics(r, bars, oos_lo, oos_hi, tf, f),
                                 "is": _metrics(r, bars, 0, oos_lo, tf, f),
                                 "post_oos_diagnostic": _metrics(r, bars, oos_hi, None, tf, f)}
        out["configs"][cfg["name"]] = row
    out["hold"] = {f"{m:g}x": {"oos": _hold(bars, oos_lo, oos_hi, cps * m, tf)}
                   for m in contract["cost_model"]["sensitivity"]}
    out["verdict"] = verdict(out)
    return out


def verdict(out: Dict[str, Any]) -> Dict[str, str]:
    """Правило контракта: Calmar выше контроля при 1× И 2×, и просадка не глубже. Иначе «не подтверждено»."""
    ctrl = out["configs"]["control"]
    res = {}
    for name, row in out["configs"].items():
        if row["role"] == "control":
            continue
        ok = True
        for m in ("1x", "2x"):
            v, c = row[m]["oos"], ctrl[m]["oos"]
            if v.get("calmar") is None or c.get("calmar") is None:
                res[name] = "UNKNOWN: Calmar не измерен"
                break
            ok &= v["calmar"] > c["calmar"] and v["max_drawdown"] >= c["max_drawdown"]
        else:
            res[name] = "лучше контроля" if ok else "не подтверждено"
    return res


if __name__ == "__main__":                       # python -m … <contract.json> <market.db копия> <отчёт.json>
    import sys
    rep = run(Path(sys.argv[1]), Path(sys.argv[2]))
    Path(sys.argv[3]).write_text(json.dumps(rep, ensure_ascii=False, indent=1, sort_keys=True))
    print(json.dumps(rep["verdict"], ensure_ascii=False), "attempt", rep["attempt"], "of", rep["attempt_budget"])
