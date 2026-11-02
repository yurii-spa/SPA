"""Пересчёт ОДНОГО forward-наблюдения по согласованному снимку (STUDIO-AUTONOMY-01 S3, E6.2 / TRP-01).

Цепочка: данные (свечи снимка) → сигнал (только по свечам ДО этого бара включительно) → цель → допуск модели
исполнения (spot: short запрещён) → виртуальное исполнение тем же ``execution.step`` из состояния книги
предыдущего наблюдения → equity (NAV). Результат сверяется с записанным наблюдением поле за полем.

Ничего не пишет: оба снимка открываются ТОЛЬКО на чтение (``mode=ro``); второй журнал истины не создаётся —
экспорт ссылается на исходные записи (seq и хеш наблюдения, кандидат и ``def_hash``, хеш снимков).
Три исхода (инв. #17): ``OK`` · ``MISMATCH`` (вход или результат отличается от записанного — названо поле) ·
``INCOMPLETE`` (вход отсутствует в снимке — догадкой не заполняется)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from . import market_data as md
from .evidence import OBS_FIELDS
from .execution import EXEC_MODELS, State, funding_in_bar, step
from .forward import _action, _data_ref
from .strategies import ASSETS, by_id

OK, MISMATCH, INCOMPLETE = "OK", "MISMATCH", "INCOMPLETE"
#: Поля наблюдения, которые цепочка обязана воспроизвести (остальные — время тика, версии, метки).
REPRODUCED = ("bar_open", "bar_close", "position_before", "fill_price", "fill_cost", "funding", "position_held",
              "equity", "target", "action", "closed_trade", "book_state", "data_ref")


def _ro(path: Path) -> sqlite3.Connection:
    from .read_model import open_ro   # одна дверь read-only (migrate_callsites)
    return open_ro(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _row(conn, sql: str, args) -> Optional[Dict[str, Any]]:
    cols = ["seq"] + list(OBS_FIELDS) + ["prev_hash", "hash"]
    r = conn.execute(sql.format(cols=",".join(cols)), args).fetchone()
    return dict(zip(cols, r)) if r else None


def replay_observation(market_db: Path, evidence_db: Path, candidate_id: str, *, seq: Optional[int] = None) -> Dict:
    """Пересчитать наблюдение ``seq`` (по умолчанию — последнее) кандидата ``candidate_id``."""
    out: Dict[str, Any] = {"candidate_id": candidate_id, "snapshot": {"market_sha256": _sha256(market_db),
                                                                     "evidence_sha256": _sha256(evidence_db)}}
    econn, mconn = _ro(evidence_db), _ro(market_db)
    try:
        where = "candidate_id=?" + (" AND seq=?" if seq is not None else "")
        args = (candidate_id, seq) if seq is not None else (candidate_id,)
        obs = _row(econn, "SELECT {cols} FROM observations WHERE " + where + " ORDER BY bar_open_time DESC LIMIT 1", args)
        if obs is None:
            return {**out, "status": INCOMPLETE, "why": "наблюдения нет в снимке evidence"}
        out["observation"] = {"seq": obs["seq"], "hash": obs["hash"], "bar_open_time": obs["bar_open_time"],
                              "code_version": obs["code_version"]}
        prev = _row(econn, "SELECT {cols} FROM observations WHERE candidate_id=? AND bar_open_time<? "
                           "ORDER BY bar_open_time DESC LIMIT 1", (candidate_id, obs["bar_open_time"]))
        reg = econn.execute("SELECT def_hash FROM candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        cand = by_id().get(candidate_id)
        if cand is None or reg is None:
            return {**out, "status": INCOMPLETE, "why": "кандидат не зарегистрирован или его определения нет в коде"}
        if cand.def_hash != reg[0]:
            return {**out, "status": MISMATCH, "why": f"определение кандидата изменилось: код {cand.def_hash} ≠ "
                                                       f"зарегистрированное {reg[0]} — это другая версия"}
        model, tf_ms = EXEC_MODELS[cand.exec_model], md.TF_MS[cand.timeframe]
        sym = ASSETS[cand.asset]
        bars = md.aggregate(md.load_1h(mconn, sym, until_ms=obs["bar_close_time"]), cand.timeframe)
        idx = next((i for i, b in enumerate(bars) if b.open_time == obs["bar_open_time"]), None)
        if idx is None or idx == 0:
            return {**out, "status": INCOMPLETE, "why": "свечи этого бара (или предыдущей) нет в снимке market"}
        bar = bars[idx]
        funding = md.funding_series(mconn, sym) if model.funding else []
        fts = [x[0] for x in funding]
        if prev:
            s = json.loads(prev["book_state"])
            st = State(equity=prev["equity"], position=prev["position_held"], qty=s.get("qty", 0.0),
                       base=s.get("base", prev["equity"]), ref=s.get("ref"), entry_eq=s.get("entry_eq"), liq=s.get("liq"))
            pending = prev["target"]
        else:
            st, pending = State(), 0
        before = st.position
        e = step(st, bar, bars[idx - 1].close, pending, model,
                 funding_rates=funding_in_bar(funding, fts, bar.open_time, tf_ms) if model.funding else ())
        target = cand.signal(bars[:idx + 1])[idx]               # только прошлое и этот бар — без заглядывания
        if not model.allow_short and target < 0:
            target = 0
        got = {"bar_open": bar.open, "bar_close": bar.close, "position_before": before, "fill_price": e["fill_price"],
               "fill_cost": e["cost"], "funding": e["funding"], "position_held": st.position, "equity": st.equity,
               "target": target, "action": _action(st.position, target),
               "closed_trade": json.dumps(e["trade"], sort_keys=True) if e["trade"] else None,
               "book_state": json.dumps({"qty": st.qty, "base": st.base, "ref": st.ref, "entry_eq": st.entry_eq,
                                         "liq": st.liq}, sort_keys=True),
               "data_ref": _data_ref(bars, idx, cand.timeframe)}
        diffs = {k: {"recorded": obs[k], "replayed": got[k]} for k in REPRODUCED if obs[k] != got[k]}
        out["chain"] = {"signal_target": target, "admitted_target": got["target"], "action": got["action"],
                        "fill_price": got["fill_price"], "cost": got["fill_cost"], "funding": got["funding"],
                        "equity": got["equity"], "prev_seq": prev["seq"] if prev else None}
        if "data_ref" in diffs:
            return {**out, "status": MISMATCH, "why": "входные свечи снимка отличаются от тех, по которым записано "
                                                      "наблюдение (data_ref)", "diffs": diffs}
        return {**out, "status": OK if not diffs else MISMATCH, "diffs": diffs,
                **({"why": "результат пересчёта отличается от записанного: " + ", ".join(diffs)} if diffs else {})}
    finally:
        econn.close()
        mconn.close()
