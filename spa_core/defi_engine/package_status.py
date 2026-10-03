"""spa_core/defi_engine/package_status.py — ONE read model of the three paper portfolios (ADR-533).

The site and the Director read the state of Conservative / Balanced / Aggressive from HERE, and this
module reads only the canonical books, the agent-health snapshot and the observation journals. It
separates three questions that used to be folded into one word («restarted», «not started»):

==========  ================================================================================
dimension   values
==========  ================================================================================
work        NOT_STARTED · RUNNING · PAUSED · FAILED · UNKNOWN — is the scheduled process doing its
                                                            job? FAILED only for a CONFIRMED fault
                                                            (non-zero exit, read-model error); a run
                                                            that is merely overdue is UNKNOWN
data        HEALTHY · WAITING_FOR_DATA · DEGRADED · STALE — did the last run see its inputs, and is
                                                            that observation still within its
                                                            documented freshness window?
decision    OPEN · HOLD · EXIT · NONE                     — what the mechanic holds / decided, and
                                                            why (a correct HOLD is not a fault)
history     WARMUP · ACCUMULATING · REPORTABLE            — how many valid periods the CURRENT
                                                            strategy version has (not the book's)
mode        PAPER_ONLY + live NOT_APPROVED · REFUSED      — real-capital admission, from the mandate
==========  ================================================================================

**Status colour is not a risk grade** (ADR-537): a green «running» says the scheduled process
works and its data is fresh — not that the package is safe, profitable, statistically proven or
allowed real money. Each question above has its own field so that no surface folds them into one
badge again. ``public_view`` is the ONE sanitised projection the site snapshot and the public API
serve; ``freshness`` carries the documented window so a reader (the browser included) can turn an
old observation into STALE by its own clock — a new ``generated_at`` never makes it fresh.

A running book whose new version has 0–1 valid periods is ``RUNNING + WARMUP`` — never
``NOT_STARTED``. A process that stopped is ``FAILED`` with the age of its last run — the site does
not keep showing a healthy launch. Unknown inputs are ``None`` with a reason (invariant #17).

Read-only; LLM_FORBIDDEN; stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

REPORTABLE_AFTER = 30          # valid periods (the main book's own go-live track minimum)
_AGENTS = {"conservative": "com.spa.daily_cycle", "balanced": "com.spa.hy_cycle", "aggressive": "com.spa.lp_cycle"}
_FILES = {"balanced": "hy_paper_trading.json", "aggressive": "lp_paper_trading.json"}
#: a run is "recent" within this many hours of its schedule (hourly sleeves, daily main book)
_FRESH_H = {"conservative": 26.0, "balanced": 2.5, "aggressive": 2.5}
#: the documented schedule each freshness window answers to (EN, RU, expected interval in hours)
_SCHEDULE = {"conservative": ("daily (cycle at 08:00 local)", "ежедневно (цикл в 08:00 по местному времени)", 24.0),
             "balanced": ("hourly; one accounting row a day", "ежечасно; одна учётная строка в день", 1.0),
             "aggressive": ("hourly; loop supervised every run, one accounting row a day",
                            "ежечасно; петля проверяется каждый запуск, одна учётная строка в день", 1.0)}


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
            # the snapshot's own time travels with the row: an exit code is a fact about the run
            # BEFORE that moment, never about a run that happened after it
            return {**a, "_snapshot_at": (health or {}).get("timestamp")}
    return None


def _work(package: str, *a, **k) -> dict:
    w = _work_state(package, *a, **k)
    w["reason_en"], w["reason_ru"] = localized_reason(w.get("reason"))
    return w


def _work_state(package: str, last_run: Optional[datetime], agent: Optional[dict], paused: Optional[str],
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
        snap_at = _ts(agent.get("_snapshot_at"))
        # Measured 2026-10-03: the 23:00Z run died on ENOSPC (exit 120), the 00:01Z run succeeded, and the
        # health snapshot taken in between kept saying 120 — the card read «not running» about a book that
        # had just written its row. A non-zero exit older than the latest successful run is history, not state.
        if snap_at is None or snap_at >= last_run:
            return {"state": "FAILED", "reason": f"last exit {agent.get('last_exit')}", "age_h": round(age, 2)}
    if age > _FRESH_H[package]:
        # overdue, but no fault is CONFIRMED (exit 0, still loaded): the honest word is UNKNOWN
        return {"state": "UNKNOWN", "reason": f"no successful run for {age:.1f} h", "age_h": round(age, 2)}
    return {"state": "RUNNING", "reason": None, "age_h": round(age, 2)}


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
    (r"USDe None|price None", "inputs not measured", "входные данные не измерены"),
    (r"kill switch tier (SOFT_DERISK|HARD_KILL)", "stop rule {0} engaged", "сработало правило остановки {0}"),
    (r"kill-switch triggers not measured", "the stop-rule triggers were not measured", "условия правила остановки не измерены"),
    (r"HARD_KILL, book moved to cash", "stop rule HARD_KILL: the book is in cash", "правило остановки HARD_KILL: книга в кэше"),
    (r"floor \(or unmeasured\)|below the 0\.97", "USDe below its price floor", "USDe ниже порога цены"),
    (r"unmeasured|not measured|no observation", "inputs not measured", "входные данные не измерены"),
    (r"CIO directive", "CIO directive: no new positions", "директива CIO: новых позиций нет"),
    (r"implied ([\d.]+) % ≥ floor ([\d.]+) %",
     "the PT fixed rate ({0} %) clears the floor ({1} %) set by the floating benchmark",
     "фиксированная ставка PT ({0} %) проходит порог ({1} %), заданный плавающей ставкой"),
    (r"position open; carry checked", "position open; carry re-checked", "позиция открыта; доходность перепроверена"),
    (r"all entry conditions met", "entry conditions met", "условия входа выполнены"),
    (r"no successful run for ([\d.]+) h", "no successful run for {0} h — cause not confirmed",
     "успешного запуска нет {0} ч — причина не подтверждена"),
    (r"last observation ([\d.]+) h old", "the last observation is {0} h old", "последнему наблюдению {0} ч"),
    (r"last exit (-?\d+)", "the last run ended with error code {0}", "последний запуск завершился с кодом ошибки {0}"),
    (r"not loaded in launchd", "the scheduled job is not loaded", "плановое задание не загружено"),
    (r"kill switch", "the book's stop rule is engaged", "сработало правило остановки книги"),
    (r"read model error", "status could not be read", "статус не удалось прочитать"),
    (r"gain_below_band", "no rebalance: the gain does not beat the cost band",
     "без ребаланса: выигрыш не перекрывает порог издержек"),
    (r"Pendle feed not ok", "Pendle data not confirmed", "данные Pendle не подтверждены"),
    (r"held pools without live evidence", "some held pools lack live evidence", "у части позиций нет живого подтверждения"),
    (r"absent or unreadable", "the book's state could not be read", "состояние книги не удалось прочитать"),
    (r"no paper state and no run recorded", "no paper state and no run recorded yet", "бумажного состояния и запусков ещё нет"),
    (r"first row", "the current version has not written its first day yet", "текущая версия ещё не записала первый день"),
)


_GENERIC_RU = "причина записана в журнале книги"
_GENERIC_EN = "reason recorded in the book's log"


def localized_reason(reason: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """People-readable EN/RU for a machine reason; unknown reasons keep EN and get a neutral RU."""
    import re
    if not reason:
        return None, None
    for pat, en, ru in _REASONS:
        m = re.search(pat, reason)
        if m:
            g = m.groups()
            return en.format(*g), ru.format(*[x.replace(".", ",") if re.fullmatch(r"-?\d+\.\d+", x or "") else x
                                              for x in g])
    return reason, _GENERIC_RU


def _history(n: int) -> str:
    return "WARMUP" if n < 2 else ("REPORTABLE" if n >= REPORTABLE_AFTER else "ACCUMULATING")


def _headline(work: dict, data: dict, hist: dict) -> tuple[str, str]:
    n = hist["valid_periods"]
    if work["state"] == "NOT_STARTED":
        return "Paper test not started", "Бумажный тест не запущен"
    _en, _ru = localized_reason(work.get("reason"))
    if work["state"] == "PAUSED":
        return f"Paper test paused — {_en}", f"Бумажный тест на паузе — {_ru}"
    if work["state"] == "UNKNOWN":
        return f"Paper test status not confirmed — {_en}", f"Статус бумажного теста не подтверждён — {_ru}"
    if work["state"] == "FAILED":
        return f"Paper test not running — {_en}", f"Бумажный тест не работает — {_ru}"
    if hist["state"] == "REPORTABLE":
        return (f"Paper test running · {n} valid days of the current version",
                f"Бумажный тест идёт · валидных дней текущей версии: {n}")
    return ("Paper test running. Statistics of the current version are accumulating "
            f"({n} valid day{'s' if n != 1 else ''} so far)",
            f"Бумажный тест запущен. Статистика текущей версии накапливается (валидных дн.: {n})")


def _observed_drawdown(equities) -> Optional[float]:
    """Worst peak-to-trough over the CURRENT version's rows, in percent (≤ 0). None = not measured."""
    vals = [float(e) for e in equities if isinstance(e, (int, float)) and e > 0]
    if not vals:
        return None
    peak, worst = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1.0)
    return round(worst * 100.0, 4)


#: decisions that are KNOWN to have been taken under a defect. The book row is never rewritten (its
#: provenance stays as written); the read model names the defect next to it, by (package, row date).
DECISION_DEFECTS = {
    ("balanced", "2026-10-02"): (
        "this decision used a defective benchmark (an aave_v3 rate spike the book does not hold; fixed in "
        "979de337) — the next scheduled decision uses the corrected rule",
        "это решение принято по дефектному ориентиру (скачок ставки aave_v3, которого нет в книге; исправлено "
        "в 979de337) — следующее плановое решение идёт по исправленному правилу"),
}


#: Protocol identities that are NOT resolved, named with the decision that owns them. `susde` (held by
#: the sleeves) and `ethena_susde` may be one asset under two keys with two different tier labels (T3 vs
#: T2); which one is right is package A of ADR-532, with the owner. Until it is decided the label is
#: not shown at all (owner, 2026-10-03, package three-portfolios-closeout item 10: «если identity
#: спорна — UNKNOWN/unresolved, а не новый выдуманный tier»).
IDENTITY_UNRESOLVED = {
    "susde": "identity vs ethena_susde not resolved (ADR-532 package A)",
    "ethena_susde": "identity vs susde not resolved (ADR-532 package A)",
}


def _composition(protocols, *, extra_en: str = "", extra_ru: str = "") -> dict:
    """Registry tier labels of the protocols the book HOLDS — measured, not a description.

    The cards used to print «Tier mix: T1 + T2» for all three packages; measured 2026-10-02 the
    Balanced book held `susde`, labelled T3 in ADAPTER_REGISTRY (the `susde`/`ethena_susde` identity
    question of ADR-532 package A is still with the owner). Tier ≠ mechanic (owner, 2026-10-02): both
    are shown, each from its own source. No label known ⇒ ``unlabelled`` (never assumed T1). The
    label comes from the canonical registry only; a protocol whose IDENTITY is unresolved shows no
    label at all — it goes to ``unresolved`` with its reason (owner, 2026-10-03, item 10). A copy that
    disagrees with the canonical registry does not change what is shown: that is the tier census's
    finding (ADR-532), not a reason to doubt the canonical label.
    """
    try:
        from spa_core.risk.concentration_monitor import _tier_map
        tmap = _tier_map()
    except Exception:  # noqa: BLE001 — absent registry is a named outcome
        tmap = None
    if tmap is None:
        return {"state": "UNMEASURED", "tiers_held": None, "source": "ADAPTER_REGISTRY unreadable"}
    held: dict = {}
    unresolved: dict = {}
    for p in protocols:
        p = str(p)
        if p in IDENTITY_UNRESOLVED:
            t = "unresolved"
            unresolved[p] = IDENTITY_UNRESOLVED[p]
        else:
            t = tmap.get(p) or "unlabelled"
        held.setdefault(t, []).append(p)
    order = sorted(held, key=lambda t: (t in ("unlabelled", "unresolved"), t))
    en = " · ".join(f"{'tier unresolved' if t == 'unresolved' else t}: {', '.join(sorted(held[t]))}"
                    for t in order) or "no positions"
    ru = (en.replace("unlabelled", "без метки").replace("tier unresolved", "тир не определён")
          if held else "позиций нет")
    out = {"state": "MEASURED", "tiers_held": {t: sorted(held[t]) for t in order},
           "unresolved": unresolved,
           "summary_en": en + extra_en, "summary_ru": ru + extra_ru,
           "source": "ADAPTER_REGISTRY tier labels of the held positions; unresolved identities withheld"}
    return out


def _decision(state: str, raw: Optional[str], reasons: list, position_en: str, position_ru: str) -> dict:
    reason = "; ".join(map(str, reasons))[:300] or None
    r_en, r_ru = localized_reason(reason)
    return {"state": state, "raw_decision": raw, "reason": reason, "reason_en": r_en, "reason_ru": r_ru,
            "position_en": position_en, "position_ru": position_ru}


def _mode(m: dict) -> dict:
    la = m.get("live_admission") or {}
    return {"state": "PAPER_ONLY", "live": la.get("state") or "NOT_APPROVED",
            "live_reason_en": la.get("reason_en"), "live_reason_ru": la.get("reason_ru")}


def _freshness(package: str, last_run_at, observed_at) -> dict:
    en, ru, every = _SCHEDULE[package]
    lr = _ts(last_run_at)
    return {"schedule_en": en, "schedule_ru": ru, "expected_every_h": every, "stale_after_h": _FRESH_H[package],
            "last_successful_run_at": last_run_at, "source_observed_at": observed_at,
            "stale_at": (lr + timedelta(hours=_FRESH_H[package])).strftime("%Y-%m-%dT%H:%M:%SZ") if lr else None}


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
        r_en, r_ru = localized_reason(w["reason"])
        return {**out, "work": {**w, "reason_en": r_en, "reason_ru": r_ru},
                "data": {"state": "WAITING_FOR_DATA", "reason": w["reason"], "reason_en": r_en, "reason_ru": r_ru},
                "decision": {"state": "NONE", "position_en": "no positions", "position_ru": "позиций нет"},
                "history": hist, "mode": _mode(m), "freshness": _freshness(package, None, None),
                "headline_en": _headline(w, {}, hist)[0], "headline_ru": _headline(w, {}, hist)[1]}
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
        _od = (last_obs or {}).get("data") or {}
        degraded = (list(last.get("fixed_carry_degraded") or []) if exp else []) or None
        if _od.get("pendle_ok") is False:   # the hourly observation outranks the daily row
            degraded = (degraded or []) + [f"Pendle feed not ok: {_od.get('pendle_reason') or 'no reason given'}"]
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
    obs_at = _ts((last_obs or {}).get("run_ts"))
    d: dict
    if not exp:
        d = {"state": "WAITING_FOR_DATA", "reason": "the current version has not written its first row yet"}
    elif last_obs is None:
        d = {"state": "WAITING_FOR_DATA", "reason": "no scheduled-run observation recorded yet"}
    elif obs_at is not None and (now - obs_at).total_seconds() / 3600.0 > _FRESH_H[package]:
        d = {"state": "STALE", "reason": f"last observation {(now - obs_at).total_seconds() / 3600.0:.1f} h old"}
    elif degraded:
        d = {"state": "DEGRADED", "reason": "; ".join(map(str, degraded))[:300]}
    else:
        d = {"state": "HEALTHY", "reason": None}
    d["reason_en"], d["reason_ru"] = localized_reason(d.get("reason"))
    d.update(last_observation_at=(last_obs or {}).get("run_ts"), feed_ok=feed_ok,
             missed_runs_24h=(PO.missed_runs(obs, expected_h=_SCHEDULE[package][2],
                                             since=(now - timedelta(hours=24)).replace(tzinfo=None),
                                             now=now.replace(tzinfo=None))
                             if obs else None),
             observations=len(obs))
    hist = {"state": _history(len(cur_rows)), "valid_periods": len(cur_rows),
            "first_period": cur_rows[0].get("date") if cur_rows else None,
            "last_period": cur_rows[-1].get("date") if cur_rows else None,
            "reportable_after": REPORTABLE_AFTER,
            "earlier_rows_kept": len(rows) - len(cur_rows),
            "observed_drawdown_pct": _observed_drawdown([h.get("equity") for h in cur_rows])}
    pos = {"count": len(st.get("positions") or []), "floating_equity_usd": st.get("floating_equity")}
    _held = [p.get("protocol") for p in (st.get("positions") or []) if isinstance(p, dict) and p.get("protocol")]
    _loop_open = package == "aggressive" and (st.get("loop") or {}).get("status") == "open"
    composition = _composition(
        _held, extra_en=" · plus the simulated Morpho Blue loop (sUSDe collateral)" if _loop_open else "",
        extra_ru=" · плюс симулированная петля Morpho Blue (залог sUSDe)" if _loop_open else "")
    if package == "balanced":
        legs = (st.get("fixed_carry") or {}).get("legs") or []
        pos.update(fixed_rate_legs=len(legs),
                   fixed_rate_value_usd=round(sum(float(l["units"]) * float(l["mark"]) for l in legs), 2))
        if legs:
            dec = _decision("OPEN", decision, reasons,
                            f"{len(legs)} PT leg(s) held to maturity, ${pos['fixed_rate_value_usd']:,.0f}",
                            f"PT в книге: {len(legs)}, держатся до погашения, "
                            + f"${pos['fixed_rate_value_usd']:,.0f}".replace(",", "\u00a0"))
        elif decision == "hold" or (exp and cur_rows):
            dec = _decision("HOLD", decision, reasons, "no PT bought — waiting for its entry conditions",
                            "PT не куплен — ждёт условий входа")
        else:
            dec = _decision("NONE", decision, reasons, "no decision of the current version yet",
                            "решений текущей версии ещё нет")
    else:
        loop = st.get("loop") or {}
        lv = loop.get("last_valuation") or {}
        is_open = loop.get("status") == "open"
        pos.update(loop_status=loop.get("status"), loop_debt_usd=lv.get("debt_value") if is_open else 0.0,
                   loop_hf=lv.get("hf") if is_open else None, loop_valued_at=lv.get("at") if is_open else None)
        if is_open:
            hf = lv.get("hf")
            hf_txt = f"{hf:.3f}" if isinstance(hf, (int, float)) else "not measured"
            hf_ru = f"{hf:.3f}".replace(".", ",") if isinstance(hf, (int, float)) else "не измерен"
            debt = lv.get("debt_value")
            debt_txt = f"${debt:,.0f}" if isinstance(debt, (int, float)) else "not measured"
            debt_ru = f"${debt:,.0f}".replace(",", "\u00a0") if isinstance(debt, (int, float)) else "не измерен"
            dec = _decision("OPEN", decision, reasons,
                            f"simulated loop open · debt {debt_txt} · health factor {hf_txt} at the last check",
                            f"симулированная петля открыта · долг {debt_ru} · фактор здоровья {hf_ru} на последней проверке")
        elif loop.get("status") in ("unwound", "liquidated", "closed") or decision in ("unwind", "liquidate"):
            dec = _decision("EXIT", decision, reasons, "loop closed by its exit rule", "петля закрыта по правилу выхода")
        elif exp and cur_rows:
            dec = _decision("HOLD", decision, reasons, "loop not opened — waiting for its entry conditions",
                            "петля не открыта — ждёт условий входа")
        else:
            dec = _decision("NONE", decision, reasons, "no decision of the current version yet",
                            "решений текущей версии ещё нет")
    dec["decision_date"] = last.get("date") if exp else None
    _df = DECISION_DEFECTS.get((package, dec["decision_date"]))
    dec["defect_en"], dec["defect_ru"] = _df if _df else (None, None)
    en, ru = _headline(w, d, hist)
    return {**out, "running_version": running_version or f"{package}-legacy-lending",
            "experiment_id": (exp or {}).get("experiment_id"),
            "experiment_started_at": (exp or {}).get("started_at"),
            "experiment_start_date": (exp or {}).get("start_date"),
            "initial_state": (exp or {}).get("initial_state"),
            "new_version_pending": pending, "work": {**w, "last_run_at": st.get("last_cycle_at")},
            "data": d, "decision": dec, "history": hist, "positions": pos, "composition": composition,
            "last_decision": {"decision": decision, "reasons": reasons[:4]},
            "mode": _mode(m), "freshness": _freshness(package, st.get("last_cycle_at"),
                                                      (last_obs or {}).get("run_ts")),
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
    # The governance writer (kill_switch.py) records the HARD tier as ``triggered``/``state`` in
    # kill_switch_status.json plus the manual flag file kill_switch_active.json; the SOFT tier lives in
    # derisk_status.json (``active``/``tier``). Read all three — the keys, not a guess (review 02.10).
    ds = _load(ddir / "derisk_status.json")
    hard = ((isinstance(ks, dict) and ks.get("triggered") is True)
            or (ddir / "kill_switch_active.json").exists()
            or (isinstance(ds, dict) and str(ds.get("tier") or "").upper() == "HARD_KILL" and ds.get("active") is True))
    soft = (not hard and isinstance(ds, dict) and ds.get("active") is True
            and str(ds.get("tier") or "").upper() == "SOFT_DERISK")
    tier = "HARD_KILL" if hard else ("SOFT_DERISK" if soft else None)
    ks_unmeasured = isinstance(ks, dict) and str(ks.get("state") or "").upper() == "UNMEASURED"
    paused = "kill switch engaged: HARD_KILL, book moved to cash" if hard else None
    w = _work("conservative", last_run, _agent(health, _AGENTS["conservative"]), paused,
              started=bool(bars or cp), now=now)
    dec = ((rat or {}).get("decision_shadow") or {})
    unev = ((dec.get("evidence") or {}).get("unevidenced_held")) or []
    obs_at = last_run
    d: dict
    if not isinstance(cp, dict):
        d = {"state": "WAITING_FOR_DATA", "reason": "current_positions.json absent or unreadable"}
    elif obs_at is not None and (now - obs_at).total_seconds() / 3600.0 > _FRESH_H["conservative"]:
        d = {"state": "STALE", "reason": f"last observation {(now - obs_at).total_seconds() / 3600.0:.1f} h old"}
    elif unev:
        d = {"state": "DEGRADED", "reason": f"held pools without live evidence: {unev}"}
    elif ks_unmeasured:
        d = {"state": "DEGRADED", "reason": "kill-switch triggers not measured"}
    else:
        d = {"state": "HEALTHY", "reason": None}
    d["last_observation_at"] = (cp or {}).get("generated_at")
    d["reason_en"], d["reason_ru"] = localized_reason(d.get("reason"))
    hist = {"state": _history(len(bars)), "valid_periods": len(bars),
            "first_period": bars[0].get("date") if bars else None,
            "last_period": bars[-1].get("date") if bars else None, "reportable_after": REPORTABLE_AFTER,
            "earlier_rows_kept": 0,
            "observed_drawdown_pct": _observed_drawdown([b.get("equity") for b in bars])}
    en, ru = _headline(w, d, hist)
    _p = (cp or {}).get("positions")
    pos: dict = _p if isinstance(_p, dict) else {}
    reasons = (dec.get("reasons") or [])[:4]
    if tier == "HARD_KILL":
        decision = _decision("EXIT", dec.get("decision"), [f"kill switch tier {tier}"],
                             "stop rule HARD_KILL: the book is moved to cash",
                             "правило остановки HARD_KILL: книга переведена в кэш")
    elif tier == "SOFT_DERISK":
        decision = _decision("HOLD", dec.get("decision"), [f"kill switch tier {tier}"],
                             "stop rule SOFT_DERISK: no new positions, hold and reduce only",
                             "правило остановки SOFT_DERISK: новых позиций нет, только удержание и сокращение")
    elif pos:
        cash = (cp or {}).get("cash_usd")
        cash_txt = f", cash ${cash:,.0f}" if isinstance(cash, (int, float)) else ""
        cash_ru = (", кэш " + f"${cash:,.0f}".replace(",", "\u00a0")) if isinstance(cash, (int, float)) else ""
        decision = _decision("OPEN", dec.get("decision"), reasons, f"{len(pos)} lending positions{cash_txt}",
                             f"позиций кредитования: {len(pos)}{cash_ru}")
    else:
        decision = _decision("NONE", dec.get("decision"), reasons, "no positions", "позиций нет")
    decision["decision_date"] = (cp or {}).get("generated_at", "")[:10] or None
    return {"package": "conservative", "mandate_version": m["strategy_version"], "running_version": m["strategy_version"],
            "mechanic": m["mechanic"], "accounting_version": m["accounting_version"], "engine": m["engine"],
            "book_file": "data/current_positions.json", "experiment_id": m["experiment_id"],
            "experiment_start_date": m["experiment_started"], "experiment_started_at": None,
            "new_version_pending": None, "work": {**w, "last_run_at": (cp or {}).get("generated_at")},
            "data": d, "decision": decision, "history": hist,
            "positions": {"count": len(pos), "cash_usd": (cp or {}).get("cash_usd")},
            "composition": _composition(list(pos.keys())),
            "last_decision": {"decision": dec.get("decision"), "reasons": reasons},
            "mode": _mode(m), "freshness": _freshness("conservative", (cp or {}).get("generated_at"),
                                                      (cp or {}).get("generated_at")),
            "equity_usd": (cp or {}).get("current_equity_usd"), "headline_en": en, "headline_ru": ru}


def _code_identity(ddir: Path, now: datetime) -> dict:
    """Which code the scheduled runs execute — from the code-sync receipt, not from a git HEAD.

    The prod tree's own git index lags origin by design (code arrives by sync, not by checkout), so
    «HEAD» proves nothing about what runs. The hourly sleeves and the daily cycle start a fresh
    process each run and execute the tree as synced; ``code_sync_status.json`` names the origin
    commit the tree matched and when that was checked. Absent / not in sync ⇒ said so.
    """
    cs = _load(ddir / "code_sync_status.json")
    if not isinstance(cs, dict):
        return {"state": "UNMEASURED", "reason": "code-sync receipt absent or unreadable"}
    at = _ts(cs.get("timestamp"))
    age = round((now - at).total_seconds() / 3600.0, 2) if at else None
    # code_sync_from_origin.sh: IN_SYNC (no drift) and SYNCED (checkout + import probe + drift re-measured 0)
    # both mean «the tree is origin_main»; FETCH_FAILED / SNAPSHOT_FAILED / CHECKOUT_FAILED / ROLLED_BACK do not
    state = "IN_SYNC" if cs.get("result") in ("IN_SYNC", "SYNCED") else "NOT_IN_SYNC"
    if state == "IN_SYNC" and (age is None or age > 2.0):
        state = "STALE_RECEIPT"
    sha = str(cs.get("origin_main") or "")
    return {"state": state, "origin_commit": sha[:12] or None, "checked_at": cs.get("timestamp"),
            "age_h": age, "result": cs.get("result")}


def build_all(data_dir: "Path | str", now: Optional[datetime] = None) -> dict:
    ddir = Path(data_dir)
    now = now or datetime.now(timezone.utc)
    health = _load(ddir / "agent_health.json")
    out = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": "PAPER", "live_capital_usd": 0,
           "agent_health_at": (health or {}).get("timestamp"), "code_identity": _code_identity(ddir, now),
           "packages": {}}
    out["packages"]["conservative"] = _conservative(ddir, health, now)
    for p in ("balanced", "aggressive"):
        try:
            out["packages"][p] = _sleeve(p, ddir, health, now)
        except Exception as exc:  # noqa: BLE001 — one broken book is named, the others still report
            from spa_core.paper_trading import strategy_mandates as SM
            r_en, r_ru = localized_reason("read model error")
            out["packages"][p] = {"package": p, "work": {"state": "FAILED", "reason": f"read model error: {exc}",
                                                         "reason_en": r_en, "reason_ru": r_ru},
                                  "data": {"state": "WAITING_FOR_DATA", "reason": None},
                                  "decision": {"state": "NONE"},
                                  "history": {"state": "WARMUP", "valid_periods": 0},
                                  "mode": _mode(SM.mandate(p)),
                                  "headline_en": "Paper status unavailable", "headline_ru": "Статус недоступен"}
    return out


#: what leaves the machine: the fields a public reader needs, nothing that names a local path,
#: a process label or a raw log. The snapshot (daily) and the public API (per request) both serve THIS.
_PUBLIC = {
    "top": ("package", "running_version", "mandate_version", "accounting_version", "experiment_id",
            "experiment_start_date", "new_version_pending", "headline_en", "headline_ru",
            "mechanic_short_en", "mechanic_short_ru"),
    "work": ("state", "reason_en", "reason_ru", "last_run_at", "age_h"),
    "data": ("state", "reason_en", "reason_ru", "last_observation_at", "missed_runs_24h", "observations"),
    "decision": ("state", "position_en", "position_ru", "reason_en", "reason_ru", "decision_date",
                 "defect_en", "defect_ru"),
    # observed_drawdown_pct stays internal (Director): a public drawdown NUMBER comes from the shelf only
    "history": ("state", "valid_periods", "first_period", "last_period", "reportable_after",
                "earlier_rows_kept"),
    "mode": ("state", "live", "live_reason_en", "live_reason_ru"),
    "composition": ("state", "tiers_held", "unresolved", "summary_en", "summary_ru"),
    "freshness": ("schedule_en", "schedule_ru", "expected_every_h", "stale_after_h",
                  "last_successful_run_at", "source_observed_at", "stale_at"),
}


_PRIVATE = None


def _scrub(v):
    """A reason that would name a file, a path or a process label is replaced by a neutral sentence."""
    import re
    global _PRIVATE
    if _PRIVATE is None:
        _PRIVATE = re.compile(r"[\w-]+\.(?:json|jsonl|py|log|plist)\b|/Users/|/tmp/|com\.spa\.|launchd")
    if isinstance(v, str) and _PRIVATE.search(v):
        return "reason recorded in the book's log" if re.search(r"[A-Za-z]{4}", v) and not re.search(
            r"[А-Яа-я]", v) else "причина записана в журнале книги"
    return v


def public_view(full: dict) -> dict:
    """The ONE sanitised projection of ``build_all`` for public surfaces (site snapshot, public API)."""
    from spa_core.paper_trading import strategy_mandates as SM
    ci = full.get("code_identity") if isinstance(full.get("code_identity"), dict) else {}
    out = {"published_at": full.get("generated_at"), "generated_at": full.get("generated_at"),
           "mode": full.get("mode"), "live_capital_usd": full.get("live_capital_usd"),
           "code_identity": {k: ci.get(k) for k in ("state", "origin_commit", "checked_at", "age_h")},
           "status_colour_is_not_a_risk_grade": True, "packages": {}}
    for name, p in (full.get("packages") or {}).items():
        if not isinstance(p, dict):
            continue
        m = SM.MANDATES.get(name) or {}
        row = {k: (p.get(k) if k in p else m.get(k)) for k in _PUBLIC["top"]}
        for dim, keys in _PUBLIC.items():
            if dim == "top":
                continue
            src = p.get(dim)
            row[dim] = {k: _scrub(src.get(k)) for k in keys} if isinstance(src, dict) else None
            if isinstance(src, dict) and isinstance(row[dim], dict):
                # an UNMATCHED machine reason (localized_reason passed it through raw) never leaves as is
                for base in ("reason", "live_reason", "position", "defect"):
                    if f"{base}_en" in row[dim] and src.get(base) and src.get(f"{base}_en") == src.get(base) \
                            and src.get(f"{base}_ru") == _GENERIC_RU:
                        row[dim][f"{base}_en"] = _GENERIC_EN
        out["packages"][name] = row
    return out
