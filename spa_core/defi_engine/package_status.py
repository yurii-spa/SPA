"""spa_core/defi_engine/package_status.py — ONE read model of the three paper portfolios (ADR-533).

The site and the Director read the state of Conservative / Balanced / Aggressive from HERE, and this
module reads only the canonical books, the agent-health snapshot and the observation journals. It
separates three questions that used to be folded into one word («restarted», «not started»):

==========  ================================================================================
dimension   values
==========  ================================================================================
work        NOT_STARTED · RUNNING · PAUSED · FAILED       — is the scheduled process doing its job?
data        HEALTHY · WAITING_FOR_DATA · DEGRADED · HOLD  — did the last run see its inputs, and is
                                                            the mechanic acting or holding (and why)?
history     WARMUP · ACCUMULATING · REPORTABLE            — how many valid periods the CURRENT
                                                            strategy version has (not the book's)
==========  ================================================================================

A running book whose new version has 0–1 valid periods is ``RUNNING + WARMUP`` — never
``NOT_STARTED``. A process that stopped is ``FAILED`` with the age of its last run — the site does
not keep showing a healthy launch. Unknown inputs are ``None`` with a reason (invariant #17).

Read-only; LLM_FORBIDDEN; stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPORTABLE_AFTER = 30          # valid periods (the main book's own go-live track minimum)
_AGENTS = {"conservative": "com.spa.daily_cycle", "balanced": "com.spa.hy_cycle", "aggressive": "com.spa.lp_cycle"}
_FILES = {"balanced": "hy_paper_trading.json", "aggressive": "lp_paper_trading.json"}
#: a run is "recent" within this many hours of its schedule (hourly sleeves, daily main book)
_FRESH_H = {"conservative": 26.0, "balanced": 2.5, "aggressive": 2.5}


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — absent / unreadable is a named outcome below
        return None


def _ts(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _agent(health: Optional[dict], label: str) -> Optional[dict]:
    for a in (health or {}).get("agents") or []:
        if isinstance(a, dict) and a.get("label") == label:
            return a
    return None


def _work(package: str, last_run: Optional[datetime], agent: Optional[dict], paused: Optional[str],
          started: bool, now: datetime) -> dict:
    if not started:
        return {"state": "NOT_STARTED", "reason": "no paper state and no run recorded"}
    if paused:
        return {"state": "PAUSED", "reason": paused}
    if agent is not None and agent.get("loaded") is False:
        return {"state": "PAUSED", "reason": f"{_AGENTS[package]} not loaded in launchd"}
    if last_run is None:
        return {"state": "FAILED", "reason": "no successful run timestamp"}
    age = (now - last_run).total_seconds() / 3600.0
    if agent is not None and agent.get("last_exit") not in (0, None):
        return {"state": "FAILED", "reason": f"last exit {agent.get('last_exit')}", "age_h": round(age, 2)}
    if age > _FRESH_H[package]:
        return {"state": "FAILED", "reason": f"no successful run for {age:.1f} h", "age_h": round(age, 2)}
    return {"state": "RUNNING", "reason": None, "age_h": round(age, 2)}


def _slot_24h_ago(now: datetime) -> str:
    from datetime import timedelta
    return (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H")


_REASONS = (
    # (regex on the machine reason, EN, RU) — the site shows people sentences, the Director the raw one
    (r"implied ([\d.]+) % < floor ([\d.]+) %",
     "the PT fixed rate ({0} %) is below the floor ({1} %) set by the floating benchmark",
     "фиксированная ставка PT ({0} %) ниже порога ({1} %), заданного плавающей ставкой"),
    (r"levered net ([\d.]+) % < unlevered",
     "the loop's net carry ({0} %) does not clear its hurdle",
     "чистая доходность петли ({0} %) не проходит порог"),
    (r"cooldown", "pause after the last exit", "пауза после последнего выхода"),
    (r"utilisation", "market utilisation above the limit", "утилизация рынка выше предела"),
    (r"spread", "borrow rate too close to the collateral yield", "ставка займа слишком близка к доходности залога"),
    (r"floor \(or unmeasured\)|below the 0\.97", "USDe below its price floor", "USDe ниже порога цены"),
    (r"unmeasured|not measured|no observation", "inputs not measured", "входные данные не измерены"),
    (r"CIO directive", "CIO directive: no new positions", "директива CIO: новых позиций нет"),
    (r"first row", "the current version has not written its first day yet", "текущая версия ещё не записала первый день"),
)


def localized_reason(reason: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """People-readable EN/RU for a machine reason; unknown reasons keep EN and get a neutral RU."""
    import re
    if not reason:
        return None, None
    for pat, en, ru in _REASONS:
        m = re.search(pat, reason)
        if m:
            return en.format(*m.groups()), ru.format(*m.groups())
    return reason, "причина записана в журнале книги"


def _history(n: int) -> str:
    return "WARMUP" if n < 2 else ("REPORTABLE" if n >= REPORTABLE_AFTER else "ACCUMULATING")


def _headline(work: dict, data: dict, hist: dict) -> tuple[str, str]:
    n = hist["valid_periods"]
    if work["state"] == "NOT_STARTED":
        return "Paper test not started", "Бумажный тест не запущен"
    if work["state"] == "PAUSED":
        return f"Paper test paused — {work['reason']}", f"Бумажный тест на паузе — {work['reason']}"
    if work["state"] == "FAILED":
        return (f"Paper test not running — {work['reason']}",
                f"Бумажный тест не работает — {work['reason']}")
    if hist["state"] == "REPORTABLE":
        return (f"Paper test running · {n} valid days of the current version",
                f"Бумажный тест идёт · {n} валидных дн. текущей версии")
    return ("Paper test running. Statistics of the current version are accumulating "
            f"({n} valid day{'s' if n != 1 else ''} so far)",
            f"Бумажный тест запущен. Статистика текущей версии накапливается (валидных дн.: {n})")


def _sleeve(package: str, ddir: Path, health: Optional[dict], now: datetime) -> dict:
    from spa_core.paper_trading import paper_observations as PO
    from spa_core.paper_trading import strategy_mandates as SM

    m = SM.mandate(package)
    st = _load(ddir / _FILES[package])
    out: dict = {"package": package, "mandate_version": m["strategy_version"], "mechanic": m["mechanic"],
                 "accounting_version": m["accounting_version"], "engine": m["engine"],
                 "book_file": f"data/{_FILES[package]}"}
    if not isinstance(st, dict):
        w = {"state": "NOT_STARTED", "reason": f"{_FILES[package]} absent or unreadable"}
        hist = {"state": "WARMUP", "valid_periods": 0}
        return {**out, "work": w, "data": {"state": "WAITING_FOR_DATA", "reason": w["reason"]},
                "history": hist, "headline_en": _headline(w, {}, hist)[0], "headline_ru": _headline(w, {}, hist)[1]}
    exp = SM.active_experiment(st)
    rows = [h for h in st.get("daily_history") or [] if isinstance(h, dict)]
    cur_rows = [h for h in rows if exp and h.get("experiment_id") == exp.get("experiment_id")]
    obs = PO.read(ddir, package)
    last_obs = obs[-1] if obs else None
    last_run = _ts(st.get("last_cycle_at"))
    if package == "balanced":
        killed = st.get("regime") == "EXIT"
    else:
        from spa_core.paper_trading.lp_cycle import IL_KILL_THRESHOLD
        dd = st.get("il_drawdown_pct")
        killed = isinstance(dd, (int, float)) and dd < IL_KILL_THRESHOLD
    paused = "book kill switch engaged (stop from peak)" if killed else None
    w = _work(package, last_run, _agent(health, _AGENTS[package]), paused,
              started=bool(rows or last_run), now=now)
    # the version the book is RUNNING vs the version the code carries
    running_version = (exp or {}).get("strategy_version")
    pending = None if running_version == m["strategy_version"] else {
        "strategy_version": m["strategy_version"], "mechanic": m["mechanic"],
        "status": "installed; its experiment opens on the book's next accounting row",
    }
    last = rows[-1] if rows else {}
    if package == "balanced":
        degraded = last.get("fixed_carry_degraded") if exp else None
        decision = last.get("fixed_carry_decision")
        reasons = last.get("fixed_carry_reasons") or []
        feed_ok = ((last_obs or {}).get("data") or {}).get("pendle_ok")
    else:
        _mok = ((last_obs or {}).get("data") or {}).get("morpho_ok")
        degraded = None if _mok is True else (((last_obs or {}).get("data") or {}).get("missing")
                                              or (["no observation recorded yet"] if _mok is None else ["feed not ok"]))
        decision = last.get("loop_decision")
        reasons = [last.get("loop_reason")] if last.get("loop_reason") else []
        feed_ok = ((last_obs or {}).get("data") or {}).get("morpho_ok")
    d: dict
    if not exp:
        d = {"state": "WAITING_FOR_DATA", "reason": "the current version has not written its first row yet"}
    elif last_obs is None:
        d = {"state": "WAITING_FOR_DATA", "reason": "no scheduled-run observation recorded yet"}
    elif degraded:
        d = {"state": "DEGRADED", "reason": "; ".join(map(str, degraded))[:300]}
    elif decision == "hold":
        d = {"state": "HOLD", "reason": "; ".join(map(str, reasons))[:300] or "no entry condition met"}
    else:
        d = {"state": "HEALTHY", "reason": None}
    d["reason_en"], d["reason_ru"] = localized_reason(d.get("reason"))
    d.update(last_observation_at=(last_obs or {}).get("run_ts"), feed_ok=feed_ok,
             missed_runs_24h=(len([g for g in PO.gaps(obs) if g >= _slot_24h_ago(now)]) if obs else None),
             observations=len(obs))
    hist = {"state": _history(len(cur_rows)), "valid_periods": len(cur_rows),
            "first_period": cur_rows[0].get("date") if cur_rows else None,
            "last_period": cur_rows[-1].get("date") if cur_rows else None,
            "reportable_after": REPORTABLE_AFTER,
            "earlier_rows_kept": len(rows) - len(cur_rows)}
    pos = {"count": len(st.get("positions") or []), "floating_equity_usd": st.get("floating_equity")}
    if package == "balanced":
        legs = (st.get("fixed_carry") or {}).get("legs") or []
        pos.update(fixed_rate_legs=len(legs),
                   fixed_rate_value_usd=round(sum(float(l["units"]) * float(l["mark"]) for l in legs), 2))
    else:
        loop = st.get("loop") or {}
        lv = loop.get("last_valuation") or {}
        pos.update(loop_status=loop.get("status"), loop_debt_usd=lv.get("debt_value") if loop.get("status") == "open" else 0.0,
                   loop_hf=lv.get("hf") if loop.get("status") == "open" else None)
    en, ru = _headline(w, d, hist)
    return {**out, "running_version": running_version or f"{package}-legacy-lending",
            "experiment_id": (exp or {}).get("experiment_id"),
            "experiment_started_at": (exp or {}).get("started_at"),
            "experiment_start_date": (exp or {}).get("start_date"),
            "initial_state": (exp or {}).get("initial_state"),
            "new_version_pending": pending, "work": {**w, "last_run_at": st.get("last_cycle_at")},
            "data": d, "history": hist, "positions": pos,
            "last_decision": {"decision": decision, "reasons": reasons[:4]},
            "equity_usd": st.get("equity"), "headline_en": en, "headline_ru": ru}


def _conservative(ddir: Path, health: Optional[dict], now: datetime) -> dict:
    from spa_core.paper_trading import strategy_mandates as SM

    m = SM.mandate("conservative")
    cp = _load(ddir / "current_positions.json")
    curve = _load(ddir / "equity_curve_daily.json")
    ks = _load(ddir / "kill_switch_status.json")
    rat = _load(ddir / "allocation_rationale.json")
    bars = [b for b in ((curve or {}).get("daily") or []) if isinstance(b, dict) and b.get("evidenced") is True]
    last_run = _ts((cp or {}).get("generated_at"))
    tier = (ks or {}).get("tier") or (ks or {}).get("state")
    paused = None
    if isinstance(ks, dict) and ks.get("active") is True:
        paused = "kill switch active"
    w = _work("conservative", last_run, _agent(health, _AGENTS["conservative"]), paused,
              started=bool(bars or cp), now=now)
    dec = ((rat or {}).get("decision_shadow") or {})
    unev = ((dec.get("evidence") or {}).get("unevidenced_held")) or []
    d: dict
    if not isinstance(cp, dict):
        d = {"state": "WAITING_FOR_DATA", "reason": "current_positions.json absent or unreadable"}
    elif unev:
        d = {"state": "DEGRADED", "reason": f"held pools without live evidence: {unev}"}
    elif str(tier or "").upper() in ("SOFT_DERISK", "HARD_KILL"):
        d = {"state": "HOLD", "reason": f"kill-switch tier {tier}"}
    else:
        d = {"state": "HEALTHY", "reason": None}
    d["last_observation_at"] = (cp or {}).get("generated_at")
    d["reason_en"], d["reason_ru"] = localized_reason(d.get("reason"))
    hist = {"state": _history(len(bars)), "valid_periods": len(bars),
            "first_period": bars[0].get("date") if bars else None,
            "last_period": bars[-1].get("date") if bars else None, "reportable_after": REPORTABLE_AFTER,
            "earlier_rows_kept": 0}
    en, ru = _headline(w, d, hist)
    _p = (cp or {}).get("positions")
    pos: dict = _p if isinstance(_p, dict) else {}
    return {"package": "conservative", "mandate_version": m["strategy_version"], "running_version": m["strategy_version"],
            "mechanic": m["mechanic"], "accounting_version": m["accounting_version"], "engine": m["engine"],
            "book_file": "data/current_positions.json", "experiment_id": m["experiment_id"],
            "experiment_start_date": m["experiment_started"], "experiment_started_at": None,
            "new_version_pending": None, "work": {**w, "last_run_at": (cp or {}).get("generated_at")},
            "data": d, "history": hist,
            "positions": {"count": len(pos), "cash_usd": (cp or {}).get("cash_usd")},
            "last_decision": {"decision": dec.get("decision"), "reasons": (dec.get("reasons") or [])[:4]},
            "equity_usd": (cp or {}).get("current_equity_usd"), "headline_en": en, "headline_ru": ru}


def build_all(data_dir: "Path | str", now: Optional[datetime] = None) -> dict:
    ddir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    health = _load(ddir / "agent_health.json")
    out = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": "PAPER", "live_capital_usd": 0,
           "agent_health_at": (health or {}).get("timestamp"), "packages": {}}
    out["packages"]["conservative"] = _conservative(ddir, health, now)
    for p in ("balanced", "aggressive"):
        try:
            out["packages"][p] = _sleeve(p, ddir, health, now)
        except Exception as exc:  # noqa: BLE001 — one broken book is named, the others still report
            out["packages"][p] = {"package": p, "work": {"state": "FAILED", "reason": f"read model error: {exc}"},
                                  "data": {"state": "WAITING_FOR_DATA", "reason": None},
                                  "history": {"state": "WARMUP", "valid_periods": 0},
                                  "headline_en": "Paper status unavailable", "headline_ru": "Статус недоступен"}
    return out
