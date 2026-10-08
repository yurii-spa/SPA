#!/usr/bin/env python3
"""Capital views (ADR-612): BTC · Trading Lab · Oracle · Sherlock — READ-ONLY, plain Russian.

One truth, not a second one. Every number on these screens comes from the SAME canonical
readers Director OS (Mission Control) is built from:

* Trading Lab / BTC — ``spa_core.trading_research.read_model.trading_lab_view`` (ADR-590), the
  function ``company_truth.capital_trading_lab`` calls;
* Oracle (CIO) — ``spa_core.investment_cio.read.latest`` (ADR-554), the function
  ``mission_control._investment_cio_section`` calls;
* Sherlock — ``spa_core.research_factory.read.latest`` → ``sherlock`` block (ADR-564), the
  function ``mission_control._research_universe_section`` calls.

Staleness thresholds are not re-declared here: the Lab's comes from ``read_model.STALE_AFTER_H``,
Oracle's and Sherlock's from Mission Control's own field ``CONTRACT`` table.

What this module deliberately does NOT do:

* import ``spa_core.studio_os.company_truth`` — ADR-580 C4: no agent reads Company Truth
  (``test_company_truth_import_ratchet.py``). The bot reads the same INPUTS instead;
* compute a financial number. It only prints what the readers measured; a value they did not
  measure is printed «не измерено» with their own reason (inv. #17), never 0;
* offer an action. Keyboards are ``nav:`` only — no ``act:``, no execution, no wallet; real
  capital is $0 and live execution is not enabled (the boundary line is on every screen).

Stdlib only, deterministic, fail-CLOSED, no LLM.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from spa_core.telegram import menus
from spa_core.telegram.views import _base as B

#: Printed on every Capital screen. A statement of POLICY (ADR-554/556/590: every engine here is
#: advisory/paper), not a measurement — the measured part is shown separately per screen.
BOUNDARY = "🔒 Реальный капитал: $0 · исполнение не включено · только бумага и исследования"
NOT_MEASURED = "не измерено"

#: Mission Control CONTRACT paths whose ``stale_after_min`` these screens reuse.
_MC_PATH_ORACLE = "capital.investment_cio"
_MC_PATH_RESEARCH = "capital.research_universe"


# ── injectable inputs (tests pass fakes; production reads the live data/ dir) ───────────────────
def _data_dir() -> Path:
    return B.DATA_DIR


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lab_view(data_dir: Path) -> Dict:
    from spa_core.trading_research.read_model import trading_lab_view
    return trading_lab_view(data_dir)


def _cio_latest(data_dir: Path, now: datetime) -> Dict:
    from spa_core.investment_cio import read as cio_read
    return cio_read.latest(data_dir, now=now)


def _research_latest(data_dir: Path) -> Dict:
    from spa_core.research_factory import read as rf_read
    return rf_read.latest(data_dir)


def _capital_sources(data_dir: Path, now: datetime) -> Dict:
    """CAPITAL-SOURCES-01 §14: the SAME projection Director OS shows (``investment_cio.sources_summary`` over
    ``investment_cio.read.capital_sources`` — the Oracle ledger's stored view). Nothing is computed here."""
    from spa_core.investment_cio import read as cio_read, sources_summary
    return sources_summary.summarize(cio_read.capital_sources(data_dir, now=now))


READERS: Dict[str, Callable[..., Any]] = {
    "lab": _lab_view, "cio": _cio_latest, "research": _research_latest, "sources": _capital_sources,
    "data_dir": _data_dir, "now": _now,
}


# ── capital sources (CAPITAL-SOURCES-01 §14) — strings come ready from the shared projection ─────────────
def _sources_doc(now: datetime) -> Tuple[Optional[Dict], Optional[str]]:
    try:
        doc = READERS["sources"](READERS["data_dir"](), now)
    except Exception as exc:  # noqa: BLE001
        return None, "источники не прочитаны ({})".format(type(exc).__name__)
    if not isinstance(doc, dict) or doc.get("state") != "MEASURED":
        from spa_core.investment_cio.sources_summary import reason_ru
        reason = (doc or {}).get("reason") if isinstance(doc, dict) else None
        return None, B_safe(reason_ru(reason) if reason else "рекомендации Oracle с разбором источников ещё не было")
    return doc, None


def _view_age_line(summary: Optional[Dict]) -> str:
    """«🕒 Разбор Oracle: 3 ч назад» + the SAME stale verdict Director shows (one constant, review P1-2)."""
    if not isinstance(summary, dict):
        return ""
    age = ((summary.get("view_age_text") or {}).get("ru")) or "возраст неизвестен"
    st = summary.get("view_stale")
    flag = " · ⚠️ УСТАРЕЛО" if st is True else (" · свежесть не проверена" if st is None else "")
    return "🕒 Разбор Oracle: {}{}".format(age, flag)


def _plain_blockers(row: Dict, limit: int = 3) -> List[str]:
    from spa_core.studio_os import owner_language as ol
    seen: List[str] = []
    for b in row.get("blockers") or []:
        t = ol.capital_blocker_plain(b)["text"]
        if t not in seen:
            seen.append(t)
    more = len(seen) - limit
    return seen[:limit] + (["…и ещё {}".format(more)] if more > 0 else [])


def trading_alpha_lines(summary: Optional[Dict], lab_doc: Optional[Dict], why: Optional[str] = None) -> List[str]:
    """The §14 block: Trading Alpha · PAPER ONLY · evidence · forward observations · champions · net · DD ·
    Oracle eligible · reason. Every value printed verbatim from the shared projection / the Lab read model."""
    lines = ["💹 Трейдинг-альфа · ТОЛЬКО БУМАГА"]
    ta = (summary or {}).get("trading_alpha") if isinstance(summary, dict) else None
    if not isinstance(ta, dict):
        lines.append("Рукав: {}".format(_nm(why or "нет в рекомендации Oracle")))
        return lines
    lines.append(_view_age_line(summary))
    tx = (ta.get("text") or {}).get("ru") or {}
    lines.append("Доказательства: {}".format(tx.get("evidence") or NOT_MEASURED))
    if isinstance(lab_doc, dict):
        fwd, _f = _cell_value(lab_doc, "forward_paper_active")
        champ, _c = _cell_value(lab_doc, "champions")
        lines.append("На форварде: {} · чемпионов: {}".format(_count(fwd), _count(champ)))
    lines.append("Чистая доходность: {}".format(tx.get("net") or NOT_MEASURED))
    lines.append("Макс. просадка: {}".format(tx.get("drawdown") or NOT_MEASURED))
    if tx.get("freshness"):
        lines.append("⚠️ {}".format(tx["freshness"]))
    el = ta.get("eligible")
    lines.append("Допуск Oracle: {}".format("ДА (бумага)" if el is True else "НЕТ" if el is False else NOT_MEASURED))
    reasons = _plain_blockers(ta)
    if reasons:
        lines.append("Почему: " + "; ".join(reasons))
    return lines


def sources_lines(summary: Optional[Dict], why: Optional[str] = None) -> List[str]:
    """Compact /capital block: one line per source + the paper portfolio + the 10–15 % research answer."""
    if not isinstance(summary, dict):
        return ["📊 Источники доходности: {}".format(_nm(why))]
    out = ["📊 Источники доходности (бумага) — " + _view_age_line(summary).replace("🕒 ", "")]
    for g in summary.get("groups") or []:
        for r in g.get("sources") or []:
            tx = (r.get("text") or {}).get("ru") or {}
            out.append("  • {}: {} · {} · вес {}".format(r.get("name_ru"), tx.get("net") or NOT_MEASURED,
                                                         tx.get("eligibility") or NOT_MEASURED,
                                                         tx.get("paper_weight") or NOT_MEASURED))
    pf = ((summary.get("portfolio") or {}).get("text") or {}).get("ru") or {}
    out.append("Бумажный портфель: {}".format(pf.get("headline") or NOT_MEASURED)
               + (" — {}".format(pf["detail"]) if pf.get("detail") else ""))
    rq = summary.get("research_question") or {}
    if rq.get("state") != "MEASURED":
        ans = "не измерено — вопрос не оценивался"
    else:
        ans = {"NO": "нет — доказательства этого не показывают", "YES": "да — по подтверждённым данным"}.get(
            rq.get("answer"), "ответа пока нет: доказательств слишком мало")
    out.append("Вопрос 10–15 % годовых: {} (исследование, не обещание)".format(ans))
    return out


def _mc_stale_after_min(path: str) -> Optional[float]:
    """Mission Control's declared freshness for a section — one place, never a copy here."""
    try:
        from spa_core.studio_os.mission_control import CONTRACT
    except Exception:  # noqa: BLE001 — unknown threshold ⇒ age is still shown, no verdict invented
        return None
    for row in CONTRACT:
        if row.get("path") == path:
            v = row.get("stale_after_min")
            return float(v) if isinstance(v, (int, float)) else None
    return None


def _mature_days() -> float:
    """The Lab's own maturity bar for a windowed return (``read_model.MATURE_30D_DAYS``)."""
    try:
        from spa_core.trading_research.read_model import MATURE_30D_DAYS
        return float(MATURE_30D_DAYS)
    except Exception:  # noqa: BLE001
        return 30.0


def _lab_stale_after_min() -> Optional[float]:
    try:
        from spa_core.trading_research.read_model import STALE_AFTER_H
        return float(STALE_AFTER_H) * 60.0
    except Exception:  # noqa: BLE001
        return None


# ── formatting helpers (no arithmetic on financial values beyond ×100 for a percent) ───────────
def _int(v: Any) -> Optional[int]:
    """An honest count: a bool is NOT a count (the Sherlock «True» defect, RM-TRUTH-01 Wave 2)."""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _capital_text(v: Any) -> str:
    """Real-capital reading: $0 only for a NUMBER equal to 0 — ``False == 0`` in Python, and a
    bool here is a malformed field, not a measurement (review P2-3)."""
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)):
        return NOT_MEASURED
    return "$0" if v == 0 else "≠ $0 — нарушение границы"


def _count(v: Any) -> str:
    n = _int(v)
    return str(n) if n is not None else NOT_MEASURED


def _owner_hhmm(now: Any) -> str:
    """«09:30 Мадрид» — owner-facing time is Europe/Madrid (ADR-660); data stays UTC."""
    from spa_core.utils.presentation import fmt_owner_time
    return fmt_owner_time(now, "ru", with_date=False, label=False, unknown="?") + " Мадрид"


def _pct(v: Any) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return NOT_MEASURED
    from spa_core.utils.presentation import fmt_pct  # ADR-660: two decimals, half-up, RU locale
    return fmt_pct(v, "ru", input="fraction", signed=True, unknown=NOT_MEASURED)


def _age_text(age_min: Optional[float]) -> str:
    if age_min is None:
        return "возраст неизвестен"
    if age_min < -10:
        return "отметка времени из будущего — данным не верю"
    if age_min < 1:
        return "только что"
    if age_min < 60:
        return "{:.0f} мин назад".format(age_min)
    if age_min < 48 * 60:
        return "{:.0f} ч назад".format(age_min / 60.0)
    return "{:.0f} дн назад".format(age_min / 1440.0)


def _parse_iso(v: Any) -> Optional[datetime]:
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def freshness_line(as_of: Optional[datetime], now: datetime, stale_after_min: Optional[float],
                   source: str) -> str:
    """«Данные: 40 мин назад · источник …» + an explicit STALE / future-stamp warning."""
    if as_of is None:
        return "🕒 Время замера неизвестно · источник: {}".format(source)
    age = (now - as_of).total_seconds() / 60.0
    line = "🕒 Данные: {} · источник: {}".format(_age_text(age), source)
    if age < -10:
        return "⛔ " + line + " — отметка из будущего, считаю НЕДОСТОВЕРНЫМ"
    if stale_after_min is not None and age > stale_after_min:
        return "⚠️ УСТАРЕЛО — " + line + " (норма свежести {})".format(_age_text(stale_after_min).replace(" назад", ""))
    return line


def _cell_value(doc: Dict, key: str) -> Tuple[Any, Optional[str]]:
    """(value, reason_if_not_measured) for one trading_lab_view cell."""
    c = doc.get(key) if isinstance(doc, dict) else None
    if not isinstance(c, dict):
        return None, "поле не отдано моделью"
    if c.get("state") in ("MEASURED", "MEASURED_ZERO"):
        return c.get("value"), None
    return None, (c.get("reason") or c.get("state") or NOT_MEASURED)


def _nm(reason: Optional[str]) -> str:
    return "{} ({})".format(NOT_MEASURED, B_safe(reason)) if reason else NOT_MEASURED


def B_safe(text: Any, limit: int = 140) -> str:
    """Reader reasons can carry absolute paths («…не найден по пути /Users/…») — strip them."""
    s = str(text or "")
    home = str(Path.home())
    s = s.replace(home, "~")
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _screen(path: str, label: str, body: List[str], footer: str, lang: str) -> Tuple[str, Dict]:
    text = B.screen(path, label, body + ["", BOUNDARY], footer, lang)
    return text, menus.standard_keyboard(path, lang)


def _safe(render: Callable[..., Tuple[str, Dict]], path: str, lang: str) -> Tuple[str, Dict]:
    """A reader that throws is «не измерено», never a crash and never a stale number."""
    try:
        return render(lang)
    except Exception as exc:  # noqa: BLE001
        body = ["Данные не прочитаны ({}). Показывать нечего — {}.".format(type(exc).__name__, NOT_MEASURED)]
        return _screen(path, "только чтение", body, "🕒 Время замера неизвестно", lang)


# ── Trading Lab ─────────────────────────────────────────────────────────────────────────────────
def _lab_doc() -> Tuple[Optional[Dict], Optional[str]]:
    try:
        doc = READERS["lab"](READERS["data_dir"]())
    except Exception as exc:  # noqa: BLE001
        return None, "модель лаборатории не прочитана ({})".format(type(exc).__name__)
    if not isinstance(doc, dict):
        return None, "модель лаборатории не прочитана"
    return doc, None


def _lab_as_of(doc: Dict) -> Optional[datetime]:
    eh = doc.get("engine_health") or {}
    ms = eh.get("as_of")
    if isinstance(ms, (int, float)) and not isinstance(ms, bool):
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return None


_HEALTH_RU = {"HEALTHY": "работает нормально", "STALE": "давно не обновлялся",
              "BROKEN": "журнал доказательств повреждён — данным не верить"}
_STAGE_RU = {"HOLD": "без изменений", "ENTER": "вход", "EXIT": "выход", "FLAT": "вне рынка"}


def _short_cid(cid: str) -> str:
    """``donchian@v1:BTC:1D:spot_long:0facf75089`` → ``donchian · 1D``."""
    parts = str(cid).split(":")
    name = parts[0].split("@")[0] if parts else str(cid)
    tf = parts[2] if len(parts) > 2 else "?"
    return "{} · {}".format(name, tf)


def render_lab(arg: str = "", lang: str = "ru", page: int = 0, prefs: Dict = None) -> Tuple[str, Dict]:
    return _safe(_render_lab, "capital.lab", lang)


def _render_lab(lang: str) -> Tuple[str, Dict]:
    now = READERS["now"]()
    doc, why = _lab_doc()
    src = "trading_lab_view (data/trading_research)"
    if doc is None:
        return _screen("capital.lab", "бумага · исследование",
                       ["Лаборатория: {}.".format(_nm(why))], freshness_line(None, now, None, src), lang)
    health, h_why = _cell_value(doc, "engine_health")
    integ, _ = _cell_value(doc, "evidence_integrity")
    cand, c_why = _cell_value(doc, "strategies_researched")
    fwd, f_why = _cell_value(doc, "forward_paper_active")
    champ, ch_why = _cell_value(doc, "champions")
    rob, _ = _cell_value(doc, "robustness_pass")
    obs, o_why = _cell_value(doc, "last_observation")
    body = ["🧪 Лаборатория торговых стратегий (канон ADR-590)", "",
            "Состояние движка: {}".format(_HEALTH_RU.get(health, _nm(h_why))),
            "Журнал доказательств: {}".format({"VERIFIED": "цел, проверен", "BROKEN": "ПОВРЕЖДЁН"}.get(integ, NOT_MEASURED)),
            "Стратегий исследовано: {}".format(_count(cand) if cand is not None else _nm(c_why)),
            "Прошли бэктест: {}".format(_count((rob or {}).get("backtest_qualified")) if isinstance(rob, dict) else NOT_MEASURED),
            "На бумажном форвард-тесте: {}".format(_count(fwd) if fwd is not None else _nm(f_why)),
            "Чемпионов: {}".format(_count(champ) if champ is not None else _nm(ch_why))]
    periods, _p = _cell_value(doc, "forward_periods")
    perf, pf_why = _cell_value(doc, "performance_since_forward_start")
    dd, _d = _cell_value(doc, "drawdown_forward")
    if isinstance(periods, dict) and periods:
        body += ["", "Форвард-тест (бумага, не деньги):"]
        for cid in sorted(periods):
            p = (perf or {}).get(cid) if isinstance(perf, dict) else None
            ret = _pct((p or {}).get("net_return")) if isinstance(p, dict) else NOT_MEASURED
            days = (p or {}).get("days_elapsed") if isinstance(p, dict) else None
            ddv = _pct((dd or {}).get(cid)) if isinstance(dd, dict) else NOT_MEASURED
            body.append("  • {} — баров {}, доходность {}{}, просадка {}".format(
                _short_cid(cid), _count(periods.get(cid)), ret,
                " за {:.0f} дн".format(days) if isinstance(days, (int, float)) and not isinstance(days, bool) else "",
                ddv))
        spans = [p.get("days_elapsed") for p in (perf or {}).values()
                 if isinstance(p, dict) and isinstance(p.get("days_elapsed"), (int, float))] if isinstance(perf, dict) else []
        if spans and max(spans) < _mature_days():
            body.append("  Годовых ставок нет: у форварда меньше {:.0f} дней истории.".format(_mature_days()))
    elif periods is None:
        body += ["", "Форвард-тест: {}".format(_nm(pf_why))]
    if isinstance(obs, dict) and obs:
        last_ms = max((v.get("bar_close_time") for v in obs.values()
                       if isinstance(v, dict) and isinstance(v.get("bar_close_time"), (int, float))), default=None)
        if last_ms is not None:
            last_dt = datetime.fromtimestamp(last_ms / 1000.0, tz=timezone.utc)
            body.append("Последнее наблюдение: бар закрыт {}".format(_age_text((now - last_dt).total_seconds() / 60.0)))
    elif obs is None:
        body.append("Последнее наблюдение: {}".format(_nm(o_why)))
    sdoc, s_why = _sources_doc(now)
    body += [""] + trading_alpha_lines(sdoc, doc, s_why)
    return _screen("capital.lab", "бумага · исследование", body,
                   freshness_line(_lab_as_of(doc), now, _lab_stale_after_min(), src), lang)


# ── BTC ─────────────────────────────────────────────────────────────────────────────────────────
_SIGN_RU = {"long": "лонг", "short": "шорт", "flat": "нейтрально"}


def render_btc(arg: str = "", lang: str = "ru", page: int = 0, prefs: Dict = None) -> Tuple[str, Dict]:
    return _safe(_render_btc, "capital.btc", lang)


def _render_btc(lang: str) -> Tuple[str, Dict]:
    now = READERS["now"]()
    doc, why = _lab_doc()
    src = "trading_lab_view → btc_signal_consensus_by_timeframe"
    head = ["₿ BTC — исследовательский сигнал, НЕ приказ на сделку", ""]
    if doc is None:
        return _screen("capital.btc", "сигнал ≠ исполнение", head + ["Сигнал: {}.".format(_nm(why))],
                       freshness_line(None, now, None, src), lang)
    breadth, b_why = _cell_value(doc, "btc_signal_consensus_by_timeframe")
    body = list(head)
    if isinstance(breadth, dict) and breadth:
        body.append("Сколько стратегий лаборатории сейчас смотрят вверх / вниз / в сторону:")
        for tf in sorted(breadth):
            counts = breadth.get(tf) or {}
            parts = ["{} {}".format(_SIGN_RU.get(k, k), _count(counts.get(k))) for k in ("long", "flat", "short")]
            body.append("  • {}: {}".format(tf, ", ".join(parts)))
        body.append("Это счёт голосов исследовательских стратегий, а не прогноз и не позиция.")
    else:
        body.append("Сигнал по таймфреймам: {}".format(_nm(b_why)))
    fwd, f_why = _cell_value(doc, "latest_btc_signal_forward")
    if isinstance(fwd, dict) and fwd:
        body += ["", "Последние сигналы стратегий на бумажном форварде:"]
        for cid in sorted(fwd):
            s = fwd.get(cid) or {}
            held = s.get("position_held")
            pos = (NOT_MEASURED if isinstance(held, bool) else "в позиции" if held == 1 else "вне позиции" if held == 0 else NOT_MEASURED)
            body.append("  • {} — {} ({})".format(_short_cid(cid), _STAGE_RU.get(s.get("action"), s.get("action") or NOT_MEASURED), pos))
    elif fwd is None:
        body += ["", "Форвард-сигналы: {}".format(_nm(f_why))]
    body.append("Отдельный продукт earn-defi (BTC-движок) сюда не суммируется (ADR-590).")
    return _screen("capital.btc", "сигнал ≠ исполнение", body,
                   freshness_line(_lab_as_of(doc), now, _lab_stale_after_min(), src), lang)


# ── Oracle (CIO) ────────────────────────────────────────────────────────────────────────────────
_STANCE_RU = {
    "INSUFFICIENT_EVIDENCE": "доказательств пока недостаточно — рекомендации нет",
    "NO_RECOMMENDATION": "ни один рискованный источник не допущен — рекомендации нет",
    "RECOMMEND": "есть рекомендация весов (только бумага)",
    "HOLD": "держать как есть", "HOLD_CASH": "держать в кэше",
    "REBALANCE": "перераспределить (на бумаге)", "DERISK": "снизить риск (на бумаге)",
}
_CONF_RU = {"LOW": "низкая", "MEDIUM": "средняя", "HIGH": "высокая"}


def render_oracle(arg: str = "", lang: str = "ru", page: int = 0, prefs: Dict = None) -> Tuple[str, Dict]:
    return _safe(_render_oracle, "capital.oracle", lang)


def _render_oracle(lang: str) -> Tuple[str, Dict]:
    now = READERS["now"]()
    src = "investment_cio.read.latest (ADR-554)"
    head = ["🔮 Oracle — директор по инвестициям (CIO)",
            "Советует, но НЕ имеет права исполнения: ни одна его рекомендация не двигает деньги.", ""]
    try:
        doc = READERS["cio"](READERS["data_dir"](), now)
    except Exception as exc:  # noqa: BLE001
        return _screen("capital.oracle", "советник · бумага",
                       head + ["Рекомендация: {} (журнал не прочитан: {}).".format(NOT_MEASURED, type(exc).__name__)],
                       freshness_line(None, now, None, src), lang)
    doc = doc if isinstance(doc, dict) else {}
    stale = _mc_stale_after_min(_MC_PATH_ORACLE)
    if doc.get("integrity") == "BROKEN":
        return _screen("capital.oracle", "советник · бумага",
                       head + ["⛔ Цепочка решений повреждена — рекомендация ОТОЗВАНА, ей не верить."],
                       freshness_line(None, now, stale, src), lang)
    if doc.get("state") != "MEASURED":
        return _screen("capital.oracle", "советник · бумага",
                       head + ["Рекомендация: {}.".format(_nm(doc.get("reason") or "рекомендаций ещё не было"))],
                       freshness_line(None, now, stale, src), lang)
    rec = doc.get("recommendation") or {}
    stance = rec.get("stance")
    chain_ok = (doc.get("ledger") or {}).get("chain_ok")
    body = list(head)
    body.append("Позиция: {}".format(_STANCE_RU.get(stance, stance or NOT_MEASURED)))
    body.append("Уверенность: {}".format(_CONF_RU.get(rec.get("confidence"), rec.get("confidence") or NOT_MEASURED)))
    body.append("Журнал решений: {}".format("цел" if chain_ok is True else "ПОВРЕЖДЁН" if chain_ok is False else NOT_MEASURED))
    complete = rec.get("evidence_cutoff_complete")
    body.append("Доказательства: {}".format(
        "все входы прочитаны" if complete is True else
        "часть входов не прочитана — вывод неполный" if complete is False else NOT_MEASURED))
    ru = doc.get("research_universe") if isinstance(doc.get("research_universe"), dict) else {}
    elig = ru.get("cio_eligible")
    body.append("Кандидатов, допущенных к его рассмотрению: {}".format(
        _count(len(elig)) if isinstance(elig, list) else NOT_MEASURED))
    executes = rec.get("executes")
    body.append("Исполняет сам: {}".format("нет" if executes is False else "ДА — это нарушение границы" if executes else NOT_MEASURED))
    body.append("Реальный капитал по его журналу: {}".format(_capital_text(rec.get("real_capital_usd"))))
    sdoc, s_why = _sources_doc(now)
    if sdoc is None:
        body += ["", "Источники доходности: {}".format(_nm(s_why))]
    else:
        body += ["", "Источники доходности, допущенные к бумажному портфелю: {} из {}".format(
            _count(sdoc.get("eligible_count")), _count(sdoc.get("risk_total"))), _view_age_line(sdoc)]
        ta = sdoc.get("trading_alpha") or {}
        el = ta.get("eligible")
        body.append("Трейдинг-альфа: {}".format("допущена (бумага)" if el is True else "не допущена" if el is False else NOT_MEASURED)
                    + ("" if el is not False else " — " + "; ".join(_plain_blockers(ta, 2))))
    return _screen("capital.oracle", "советник · бумага", body,
                   freshness_line(_parse_iso(rec.get("generated_at")), now, stale, src), lang)


# ── Sherlock (Head of Research) ─────────────────────────────────────────────────────────────────
_GATE_RU = {
    "fees_measured": "не измерены комиссии",
    "net_return_computable": "нельзя посчитать чистую доходность",
    "paper_accounting_feasible": "нельзя вести бумажный учёт",
    "data_fresh": "данные несвежие",
    "forward_collection_ready": "не готов сбор форвард-данных",
    "identity_verified": "не подтверждена личность эмитента",
    "return_source_verified": "не подтверждён источник доходности",
}


def render_sherlock(arg: str = "", lang: str = "ru", page: int = 0, prefs: Dict = None) -> Tuple[str, Dict]:
    return _safe(_render_sherlock, "capital.sherlock", lang)


def _render_sherlock(lang: str) -> Tuple[str, Dict]:
    now = READERS["now"]()
    src = "research_factory.read.latest → sherlock (ADR-564)"
    head = ["🔎 Sherlock — глава исследований",
            "Проверяет доказательства по кандидатам. Права двигать капитал у него нет.", ""]
    try:
        doc = READERS["research"](READERS["data_dir"]())
    except Exception as exc:  # noqa: BLE001
        return _screen("capital.sherlock", "исследование", head + ["Реестр: {} ({}).".format(NOT_MEASURED, type(exc).__name__)],
                       freshness_line(None, now, None, src), lang)
    doc = doc if isinstance(doc, dict) else {}
    stale = _mc_stale_after_min(_MC_PATH_RESEARCH)
    if doc.get("integrity") == "BROKEN":
        return _screen("capital.sherlock", "исследование",
                       head + ["⛔ Журнал фабрики исследований повреждён — счётчикам не верить."],
                       freshness_line(None, now, stale, src), lang)
    sh = doc.get("sherlock")
    if not doc.get("schema") or not isinstance(sh, dict):
        return _screen("capital.sherlock", "исследование", head + ["Сводка Sherlock: {}.".format(NOT_MEASURED)],
                       freshness_line(_parse_iso(doc.get("generated_at")), now, stale, src), lang)
    denom = doc.get("denominators") or {}
    body = list(head)
    body.append("Просмотрено рынков (последний прогон): {}".format(_count(denom.get("scanned"))))
    body.append("Найдено кандидатов: {}".format(_count(denom.get("discovered"))))
    reviewed = sh.get("reviewed_today")
    body.append("Проверял сегодня: {}".format("да" if reviewed is True else "нет" if reviewed is False else NOT_MEASURED))
    body.append("С готовыми доказательствами: {}".format(_count(sh.get("evidence_ready"))))
    body.append("На бумажном тесте: {}".format(_count(sh.get("paper_active"))))
    body.append("Допущено к Oracle: {}".format(_count(sh.get("cio_eligible"))))
    body.append("Контрагент неизвестен: {}".format(_count(sh.get("counterparty_unknown"))))
    body.append("Устаревшие доказательства: {}".format(_count(sh.get("stale_evidence"))))
    blockers = [b for b in (sh.get("top_blockers") or []) if isinstance(b, dict) and b.get("gate")]
    if blockers:
        body += ["", "Чаще всего мешает:"]
        for b in blockers[:5]:
            body.append("  • {} — {}".format(_GATE_RU.get(b["gate"], b["gate"]), _count(b.get("count"))))
    body.append("«Всего фактов» не показываю: этот источник такого числа не отдаёт.")
    return _screen("capital.sherlock", "исследование", body,
                   freshness_line(_parse_iso(doc.get("generated_at")), now, stale, src), lang)


# ── Capital overview ────────────────────────────────────────────────────────────────────────────
def render_menu(arg: str = "", lang: str = "ru", page: int = 0, prefs: Dict = None) -> Tuple[str, Dict]:
    return _safe(_render_menu, "capital", lang)


def _render_menu(lang: str) -> Tuple[str, Dict]:
    now = READERS["now"]()
    body = ["💼 Капитал — что исследуется и что ведётся на бумаге", ""]
    doc, why = _lab_doc()
    live_cap = None
    if doc is not None:
        cand, _c = _cell_value(doc, "strategies_researched")
        fwd, _f = _cell_value(doc, "forward_paper_active")
        live_cap, _l = _cell_value(doc, "live_capital")
        body.append("🧪 Лаборатория: стратегий {}, на форварде {}".format(_count(cand), _count(fwd)))
    else:
        body.append("🧪 Лаборатория: {}".format(_nm(why)))
    try:
        cio = READERS["cio"](READERS["data_dir"](), now) or {}
        if cio.get("integrity") == "BROKEN":
            body.append("🔮 Oracle: ⛔ цепочка решений повреждена — рекомендация отозвана, не верить")
        else:
            rec = (cio.get("recommendation") or {}) if cio.get("state") == "MEASURED" else {}
            stance = rec.get("stance")
            if stance:
                # review P2-2: the stance carries its age and the same STALE rule as the Oracle screen
                at = _parse_iso(rec.get("generated_at"))
                stale = _mc_stale_after_min(_MC_PATH_ORACLE)
                age = (now - at).total_seconds() / 60.0 if at else None
                flag = (" · ⚠️ УСТАРЕЛО" if (age is not None and stale is not None and age > stale) else "")
                body.append("🔮 Oracle: {} ({}{})".format(_STANCE_RU.get(stance, stance), _age_text(age), flag))
            else:
                body.append("🔮 Oracle: {}".format(NOT_MEASURED))
    except Exception as exc:  # noqa: BLE001
        body.append("🔮 Oracle: {} ({})".format(NOT_MEASURED, type(exc).__name__))
    try:
        rf = READERS["research"](READERS["data_dir"]()) or {}
        sh = rf.get("sherlock")
        # review P1-2: the same gates as the Sherlock screen (and as Mission Control, which sets
        # sherlock=None on BROKEN) — a broken journal's counter is never printed as a number.
        if rf.get("integrity") == "BROKEN":
            body.append("🔎 Sherlock: ⛔ журнал фабрики исследований повреждён — счётчикам не верить")
        elif not rf.get("schema") or not isinstance(sh, dict):
            body.append("🔎 Sherlock: {}".format(NOT_MEASURED))
        else:
            body.append("🔎 Sherlock: с готовыми доказательствами {}".format(_count(sh.get("evidence_ready"))))
    except Exception as exc:  # noqa: BLE001
        body.append("🔎 Sherlock: {} ({})".format(NOT_MEASURED, type(exc).__name__))
    sdoc, s_why = _sources_doc(now)
    body += [""] + sources_lines(sdoc, s_why)
    body += ["", "Реальный капитал по журналу лаборатории: {}".format(_capital_text(live_cap))]
    body.append("Кнопки ниже только открывают экраны — действий с деньгами здесь нет.")
    return _screen("capital", "только чтение", body,
                   "🕒 Сводка собрана {}".format(_owner_hhmm(now)), lang)
