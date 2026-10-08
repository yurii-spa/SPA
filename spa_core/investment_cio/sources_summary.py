"""Capital Sources — the ONE owner-facing projection of the Oracle's capital-sources view (CAPITAL-SOURCES-01 §13–14).

Director OS (through Company Truth) and the Telegram Capital screens both show the same four return sources,
the Trading Alpha sleeve, the PAPER portfolio and the 10–15 % research question. Neither of them may compute
any of it: the numbers are produced ONCE by the Oracle's daily run (``sources_portfolio.view`` → ledger →
``read.capital_sources``). This module only PROJECTS that stored view into compact rows that both surfaces
render — so a value can never differ between the cockpit and the bot (seam test:
``spa_core/tests/test_company_truth_capital_sources.py``).

Rules (inv. #17, ADR-640/641):

* an absent cell stays absent — ``{"value": None, "state": "NOT_MEASURED", …}`` — never 0;
* a source's paper weight is ``None`` when the portfolio itself was not measured or was refused, and an
  explicit ``0.0`` only when a MEASURED portfolio holds nothing of it;
* nothing here executes or recommends; ``executes`` is always False and ``real_capital_usd`` always 0.

Pure, stdlib, deterministic, no I/O.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SCHEMA = "capital-sources-summary/1"

#: display order of the four source types (§2 / §13)
SOURCE_TYPES = ("DEFI_YIELD", "TRADING_ALPHA", "MARKET_NEUTRAL_BASIS", "TREASURY_CASH")

#: owner-facing names — one table for both surfaces
TYPE_NAME = {
    "DEFI_YIELD": {"ru": "Доходность DeFi", "en": "DeFi Yield"},
    "TRADING_ALPHA": {"ru": "Трейдинг-альфа", "en": "Trading Alpha"},
    "MARKET_NEUTRAL_BASIS": {"ru": "Рыночно-нейтральный базис", "en": "Market-neutral / basis"},
    "TREASURY_CASH": {"ru": "Кэш", "en": "Cash"},
}
SOURCE_NAME = {
    "defi_conservative": {"ru": "Консервативный", "en": "Conservative"},
    "defi_balanced": {"ru": "Сбалансированный", "en": "Balanced"},
    "defi_aggressive": {"ru": "Агрессивный", "en": "Aggressive"},
    "trading_alpha": {"ru": "Трейдинг-альфа (бумажный рукав)", "en": "Trading Alpha (paper sleeve)"},
    "market_neutral_basis": {"ru": "Базис (наблюдение)", "en": "Basis (observe-only)"},
    "cash": {"ru": "Кэш", "en": "Cash"},
}

RESEARCH_TARGET_NOTE = {
    "ru": "Это исследовательский вопрос, а не цель и не обещание: система вправе ответить «нет».",
    "en": "A research question, not a target or a promise: the system is allowed to answer «no».",
}

_ABSENT = "NOT_MEASURED"
_DEF = "DEFINITIONAL"

#: ONE freshness contract for the Oracle's capital-sources view: Mission Control's CONTRACT row
#: ``capital.capital_sources`` and the Telegram screens both read this constant (review P1-2).
VIEW_STALE_AFTER_MIN = 1800


def _cell(c: Any, why: str = "absent from the view") -> Dict:
    """A typed cell, absent kept absent (inv. #17)."""
    if not isinstance(c, dict):
        return {"value": None, "state": _ABSENT, "unit": None, "as_of": None, "reason": why, "note": None}
    return {"value": c.get("value"), "state": c.get("state") or _ABSENT, "unit": c.get("unit"),
            "as_of": c.get("as_of"), "reason": c.get("reason"), "note": c.get("note")}


def _freshness_state(src: Dict) -> str:
    """STALE when either the freshness cell or its measured value says so — the same two places
    ``sources_portfolio._is_stale`` reads; NOT_MEASURED when there is nothing to judge."""
    f = src.get("freshness")
    if not isinstance(f, dict):
        return _ABSENT
    if f.get("state") == "STALE":
        return "STALE"
    v = f.get("value")
    if isinstance(v, dict) and v.get("state") == "STALE":
        return "STALE"
    return f.get("state") or _ABSENT


def _portfolio(pf: Any) -> Dict:
    if not isinstance(pf, dict):
        return {"state": _ABSENT, "reason": "no paper portfolio in the view", "weights": None, "cash": None,
                "metrics": {}, "basis": None, "reconstruction": None, "window": None}
    refused = pf.get("state") == "REFUSED"
    metrics = pf.get("metrics") if isinstance(pf.get("metrics"), dict) else {}
    nav = metrics.get("nav") if isinstance(metrics.get("nav"), dict) else {}
    invested = nav.get("state") not in (None, _ABSENT) and not refused
    return {"state": "REFUSED" if refused else ("MEASURED" if invested else _ABSENT),
            "reason": pf.get("reason") if refused else (nav.get("reason") if not invested else None),
            "weights": None if refused else (pf.get("weights") if isinstance(pf.get("weights"), dict) else None),
            "cash": None if refused else pf.get("cash"),
            "metrics": {k: _cell(v) for k, v in sorted(metrics.items())},
            "basis": pf.get("basis"), "reconstruction": pf.get("reconstruction"), "window": pf.get("window")}


def _paper_weight(sid: str, portfolio: Dict) -> Optional[float]:
    w = portfolio.get("weights")
    if not isinstance(w, dict):
        return None                       # portfolio refused / absent ⇒ the weight is not known
    v = w.get(sid)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return 0.0                            # a measured portfolio that holds nothing of this source


def _correlation(matrix: Any) -> Dict:
    """Counts only — which pairs have a measured correlation and why the rest do not."""
    if not isinstance(matrix, dict):
        return {"state": _ABSENT, "pairs": 0, "measured": 0, "by_state": {}}
    seen, by_state, measured = set(), {}, 0
    for a, row in matrix.items():
        if not isinstance(row, dict):
            continue
        for b, c in row.items():
            key = tuple(sorted((str(a), str(b))))
            if key in seen or key[0] == key[1]:
                continue
            seen.add(key)
            st = (c or {}).get("state") if isinstance(c, dict) else _ABSENT
            st = st or _ABSENT
            by_state[st] = by_state.get(st, 0) + 1
            if st == "MEASURED":
                measured += 1
    return {"state": "MEASURED" if seen and measured == len(seen) else ("NOT_ENOUGH_HISTORY" if seen else _ABSENT),
            "pairs": len(seen), "measured": measured, "by_state": dict(sorted(by_state.items()))}


# ── one formatter for both surfaces (the cockpit and the bot print these strings verbatim) ─────────────
_STATE_TEXT = {
    "ru": {"NOT_MEASURED": "не измерено", "NOT_ENOUGH_HISTORY": "мало истории", "STALE": "устарело",
           "CORRUPT": "данные повреждены", "REFUSED": "отклонено", "UNKNOWN": "неизвестно",
           "UNDEFINED": "не определено"},
    "en": {"NOT_MEASURED": "not measured", "NOT_ENOUGH_HISTORY": "not enough history", "STALE": "stale",
           "CORRUPT": "data corrupt", "REFUSED": "refused", "UNKNOWN": "unknown", "UNDEFINED": "undefined"},
}


def _num(x: Any) -> Optional[float]:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _fmt_pct(fraction: float, lang: str, *, digits: int = 2, signed: bool = True, floor: bool = False) -> str:
    """Presentation only (ADR-660, owner 2026-10-08): two decimals, ROUND_HALF_UP, one formatter
    for every owner surface. ``digits``/``floor`` (ADR-563's round-down) are kept in the signature
    and no longer read — the owner superseded both; the underlying number is untouched."""
    from spa_core.utils.presentation import fmt_pct
    s = fmt_pct(fraction, "ru" if lang == "ru" else "en", input="fraction", signed=signed, unknown="?")
    return s.replace("-", "−")


def _ddmm(v: Any) -> Optional[str]:
    """«30.09» from an ISO date/timestamp; None when absent or unreadable (never today's date)."""
    if not isinstance(v, str) or len(v) < 10 or v[4] != "-" or v[7] != "-":
        return None
    return f"{v[8:10]}.{v[5:7]}"


def _since(row_or_window: Dict, lang: str, start_key: str = "evidence_start", end_key: str = "as_of") -> str:
    """«с 30.09, на 08.10» — the window a cumulative figure covers, said instead of «с начала»."""
    st = row_or_window.get(start_key)
    st = st.get("value") if isinstance(st, dict) else st
    en = row_or_window.get(end_key)
    en = en.get("value") if isinstance(en, dict) else en
    a, b = _ddmm(st), _ddmm(en)
    if lang == "ru":
        return (f" с {a}" if a else " с начала (дата начала не записана)") + (f", на {b}" if b else "")
    return (f" from {a}" if a else " since inception (start date not recorded)") + (f" to {b}" if b else "")


def _state_text(cell: Dict, lang: str) -> str:
    return _STATE_TEXT[lang].get(cell.get("state") or _ABSENT, _STATE_TEXT[lang]["NOT_MEASURED"])


def _measured(cell: Dict) -> Optional[float]:
    return _num(cell.get("value")) if cell.get("state") in ("MEASURED", "MEASURED_ZERO") else None


def row_text(row: Dict, lang: str) -> Dict[str, str]:
    """The owner strings for one source row — absent stays «не измерено», never «0 %»."""
    nm = _STATE_TEXT[lang]["NOT_MEASURED"]
    net, ann = _measured(row["net_return"]), _measured(row["annualized_return"])
    definitional = row["annualized_return"].get("state") == _DEF and net is None
    if definitional:
        net_t = ("0 % по определению (кэш не начисляет доход)" if lang == "ru"
                 else "0% by definition (idle cash earns nothing)")
    elif net is not None:
        net_t = _fmt_pct(net, lang) + _since(row, lang)
        if ann is not None:
            net_t += " · " + _fmt_pct(ann, lang, digits=1, signed=False, floor=True) + (" годовых" if lang == "ru" else " annualised")
    elif ann is not None:
        net_t = _fmt_pct(ann, lang, digits=1, signed=False, floor=True) + (" годовых" if lang == "ru" else " annualised")
    else:
        net_t = _state_text(row["net_return"] if row["net_return"].get("state") != _ABSENT else row["annualized_return"], lang)
    dd = _measured(row["drawdown"])
    if row["drawdown"].get("state") == _DEF:
        dd_t = "нет по определению (кэш не падает в цене)" if lang == "ru" else "none by definition (idle cash)"
    else:
        dd_t = _fmt_pct(dd, lang, signed=dd < 0) if dd is not None else _state_text(row["drawdown"], lang)
    days, obs = _measured(row["evidence_days"]), _measured(row["observations"])
    days_t = (f"{days:.1f}".replace(".", ",") + " календарных дн.") if (days is not None and lang == "ru") else \
             (f"{days:.1f} calendar days" if days is not None else _state_text(row["evidence_days"], lang))
    obs_t = (f"{int(obs)} " + ("наблюдений" if lang == "ru" else "observations")) if obs is not None \
        else _state_text(row["observations"], lang)
    elig = row.get("eligible")
    mw = _num(row.get("max_paper_weight"))
    if elig is True:
        elig_t = (f"допущен до {mw * 100:.0f} % (бумага)" if lang == "ru" else f"eligible up to {mw * 100:.0f}% (paper)") \
            if mw is not None else ("допущен (бумага)" if lang == "ru" else "eligible (paper)")
    elif elig is False:
        elig_t = "не допущен" if lang == "ru" else "not eligible"
    else:
        elig_t = "не оценено" if lang == "ru" else "not assessed"
    w = row.get("paper_weight")
    w_t = (f"{w * 100:.0f} %" if lang == "ru" else f"{w * 100:.0f}%") if isinstance(w, float) else nm
    conf_cell = row["confidence"]
    conf = conf_cell.get("value") if conf_cell.get("state") in ("MEASURED", _DEF) else None
    conf_t = {"ru": {"LOW": "низкая", "MEDIUM": "средняя", "HIGH": "высокая"},
              "en": {"LOW": "low", "MEDIUM": "medium", "HIGH": "high"}}[lang].get(str(conf), nm) if conf else nm
    if conf and conf_cell.get("state") == _DEF:
        conf_t += " (по определению)" if lang == "ru" else " (by definition)"
    fresh_t = ("данные устарели" if lang == "ru" else "data stale") if row.get("freshness_state") == "STALE" else ""
    return {"net": net_t, "drawdown": dd_t, "evidence": f"{days_t} · {obs_t}", "eligibility": elig_t,
            "paper_weight": w_t, "confidence": conf_t, "freshness": fresh_t}


def portfolio_text(pf: Dict, lang: str) -> Dict[str, str]:
    m = pf.get("metrics") or {}
    if pf.get("state") != "MEASURED":
        why = pf.get("reason") or ""
        head = _STATE_TEXT[lang].get(pf.get("state") or _ABSENT, _STATE_TEXT[lang]["NOT_MEASURED"])
        if lang == "ru" and why == "nothing invested":
            why = "ни один источник пока не допущен — бумажный портфель целиком в кэше"
        return {"headline": head, "detail": why}
    nav = _measured(m.get("nav") or {})
    net = _measured(m.get("net_return") or {})
    ann = _measured(m.get("annualized_return") or {})
    dd = _measured(m.get("max_drawdown") or {})
    parts = []
    if net is not None:
        parts.append(_fmt_pct(net, lang) + _since(pf.get("window") or {}, lang, "from", "to"))
    if ann is not None:
        parts.append(_fmt_pct(ann, lang, digits=1, signed=False, floor=True) + (" годовых" if lang == "ru" else " annualised"))
    if dd is not None:
        parts.append(("просадка " if lang == "ru" else "max DD ") + _fmt_pct(dd, lang, signed=dd < 0))
    head = " · ".join(parts) or _STATE_TEXT[lang]["NOT_MEASURED"]
    label = "Без заглядывания вперёд: веса — те, что были известны на тот день" if lang == "ru" else \
        "No look-ahead: weights are those knowable on each day"
    return {"headline": head, "detail": label, "nav": (f"{nav:.4f}" if nav is not None else "")}


def _age_ru(age_min: Optional[float]) -> str:
    if age_min is None:
        return "возраст неизвестен"
    if age_min < 60:
        return f"{max(age_min, 0):.0f} мин назад"
    if age_min < 48 * 60:
        return f"{age_min / 60:.0f} ч назад"
    return f"{age_min / 1440:.0f} дн назад"


def _age_en(age_min: Optional[float]) -> str:
    if age_min is None:
        return "age unknown"
    if age_min < 60:
        return f"{max(age_min, 0):.0f} min ago"
    if age_min < 48 * 60:
        return f"{age_min / 60:.0f} h ago"
    return f"{age_min / 1440:.0f} d ago"


#: plain-Russian owner text for the known «view absent» reasons; the technical reason stays in ``reason``
_ABSENT_REASON_RU = (
    ("predates the capital-sources view", "последний разбор Oracle сделан до появления разбора источников — "
                                          "он появится после следующего ежедневного запуска Oracle"),
    ("no verified recommendation", "у Oracle пока нет проверенной рекомендации"),
    ("no capital-sources view", "разбора источников у Oracle пока нет"),
)


def reason_ru(reason: Any) -> str:
    """Owner-facing Russian for an absent view; an unknown reason is NOT guessed — it says so."""
    text = str(reason or "")
    for needle, ru in _ABSENT_REASON_RU:
        if needle in text:
            return ru
    return "разбор источников недоступен (причина — в технических подробностях)"


def summarize(view: Any) -> Dict:
    """The capital-sources view (as served by ``investment_cio.read.capital_sources``) → owner rows."""
    if not isinstance(view, dict) or view.get("state") != "MEASURED":
        st = (view or {}).get("state") if isinstance(view, dict) else None
        return {"schema": SCHEMA, "state": st if st in ("REFUSED", _ABSENT) else _ABSENT,
                "reason": (view or {}).get("reason") if isinstance(view, dict) else "no capital-sources view",
                "reason_ru": reason_ru((view or {}).get("reason") if isinstance(view, dict) else "no capital-sources view"),
                "executes": False, "real_capital_usd": 0}
    by_source = ((view.get("assessment") or {}).get("by_source") or {}) if isinstance(view.get("assessment"), dict) else {}
    portfolio = _portfolio(view.get("paper_portfolio"))
    rows: List[Dict] = []
    for s in view.get("sources") or []:
        if not isinstance(s, dict) or not s.get("source_id"):
            continue
        sid = str(s["source_id"])
        a = by_source.get(sid) if isinstance(by_source.get(sid), dict) else {}
        q = a.get("qualifies")
        names = SOURCE_NAME.get(sid) or {"ru": s.get("name") or sid, "en": s.get("name") or sid}
        rows.append({
            "source_id": sid, "source_type": s.get("source_type"), "name_ru": names["ru"], "name_en": names["en"],
            "status": s.get("status"),
            "lifecycle_stage": _cell(s.get("lifecycle_stage")),
            "net_return": _cell(s.get("net_return")),
            "annualized_return": _cell(s.get("annualized_return")),
            "drawdown": _cell(s.get("drawdown")),
            "evidence_days": _cell(s.get("evidence_days")),
            "observations": _cell(s.get("observations")),
            "confidence": _cell(s.get("confidence")),
            "evidence_start": _cell(s.get("evidence_start")),
            "as_of": (s.get("measurement_as_of") or {}).get("value") if isinstance(s.get("measurement_as_of"), dict) else None,
            "freshness_state": _freshness_state(s),
            # eligibility = the Oracle's own assessment; None when it said nothing (never «eligible» by default)
            "eligible": q if isinstance(q, bool) else None,
            "max_paper_weight": a.get("max_paper_weight"),
            "paper_weight": _paper_weight(sid, portfolio),
            "statement": a.get("statement"),
            "blockers": [str(b) for b in (a.get("blockers") if a.get("blockers") is not None
                                          else s.get("blockers") or [])],
        })
    for r in rows:
        r["text"] = {"ru": row_text(r, "ru"), "en": row_text(r, "en")}
    portfolio["text"] = {"ru": portfolio_text(portfolio, "ru"), "en": portfolio_text(portfolio, "en")}
    groups = [{"source_type": t, "name_ru": TYPE_NAME[t]["ru"], "name_en": TYPE_NAME[t]["en"],
               "sources": [r for r in rows if r["source_type"] == t]} for t in SOURCE_TYPES]
    ta = next((r for r in rows if r["source_type"] == "TRADING_ALPHA"), None)
    fr = view.get("frontier") if isinstance(view.get("frontier"), dict) else None
    if fr is None:
        research = {"state": _ABSENT, "answer": None, "question": None, "verdict": None,
                    "reason": "the view carries no frontier (research question not evaluated)"}
    else:
        research = {"state": "MEASURED", "question": fr.get("question"), "answer": fr.get("answer") or "UNKNOWN",
                    "verdict": fr.get("verdict"), "realized_best_within_caps": fr.get("realized_best_within_caps")}
    research.update({"note_ru": RESEARCH_TARGET_NOTE["ru"], "note_en": RESEARCH_TARGET_NOTE["en"]})
    risky = [r for r in rows if r.get("source_type") != "TREASURY_CASH"]
    age_h = _num(view.get("age_hours"))
    age_min = age_h * 60.0 if age_h is not None else None
    stale = None if age_min is None else age_min > VIEW_STALE_AFTER_MIN
    return {
        "schema": SCHEMA, "state": "MEASURED", "as_of": view.get("as_of"),
        "recommendation_date": view.get("recommendation_date"), "oracle_stance": view.get("oracle_stance"),
        "age_hours": view.get("age_hours"), "ledger_chain_ok": view.get("ledger_chain_ok"),
        # freshness of the VIEW itself, by the one contract; None = age unknown (never «fresh» by default)
        "view_stale": stale, "view_stale_after_min": VIEW_STALE_AFTER_MIN,
        "view_age_text": {"ru": _age_ru(age_min), "en": _age_en(age_min)},
        "eligible_count": len([r for r in risky if r.get("eligible") is True]),
        "risk_total": len(risky),
        "capital_mode": "PAPER", "executes": False, "real_capital_usd": 0,
        "groups": groups, "rows": rows, "trading_alpha": ta, "portfolio": portfolio,
        "research_question": research,
        "correlation": _correlation(view.get("correlation_matrix")),
    }


__all__ = ["SCHEMA", "SOURCE_TYPES", "TYPE_NAME", "SOURCE_NAME", "VIEW_STALE_AFTER_MIN", "summarize", "row_text",
           "portfolio_text"]
