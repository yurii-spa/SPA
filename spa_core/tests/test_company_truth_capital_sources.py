"""CAPITAL-SOURCES-01 §13–14 — Director OS and Telegram show the SAME capital-sources truth.

Both surfaces print the strings of ONE projection (``investment_cio.sources_summary``) of the Oracle's
stored view. These tests pin: absent stays «не измерено» (inv. #17), UNKNOWN is never green, a stale
source is flagged, gross is never printed as net, every blocker template has a Russian phrase, the two
surfaces cannot disagree, and nothing here can act.
"""
# FROZEN-DATE-OK: literal ISO dates here are the SUBJECT (the «с ДД.ММ, на ДД.ММ» rendering of a stored window); freshness is judged only from injected age_hours, never a clock
from __future__ import annotations

import ast
import copy
import re
from pathlib import Path

from spa_core.investment_cio import sources_summary as ss
from spa_core.studio_os import company_truth as ct
from spa_core.studio_os import owner_language as ol
from spa_core.telegram.views import capital as tg

REPO = Path(__file__).resolve().parents[2]
AS_OF = "T0-fixture-label"   # opaque label: freshness comes from the injected age_min/age_hours, never a clock


def _m(value, unit=None, n=None, note=None, state="MEASURED"):
    return {"value": value, "state": state, "unit": unit, "as_of": AS_OF, "n": n, "note": note, "reason": None,
            "source": "fixture"}


def _nm(reason="not measured in the fixture", state="NOT_MEASURED"):
    return {"value": None, "state": state, "unit": None, "as_of": None, "n": None, "note": None,
            "reason": reason, "source": None}


def _source(sid, stype, **cells):
    base = {k: _nm() for k in ("lifecycle_stage", "net_return", "gross_return", "annualized_return", "drawdown",
                                "evidence_days", "observations", "confidence", "freshness")}
    base.update(cells)
    base.update({"source_id": sid, "source_type": stype, "name": sid, "status": "ALLOCATABLE_PAPER",
                 "blockers": []})
    return base


def _view():
    sources = [
        _source("defi_conservative", "DEFI_YIELD", annualized_return=_m(0.048943, "fraction_annualized"),
                drawdown=_m(-0.000393, "fraction"), evidence_days=_m(106, "valid periods"),
                confidence=_m("MEDIUM"), freshness=_m({"state": "FRESH"})),
        _source("trading_alpha", "TRADING_ALPHA", net_return=_m(0.0004423, "fraction, cumulative"),
                gross_return=_m(0.0021392, "fraction, cumulative"), drawdown=_m(-0.0122425, "fraction"),
                evidence_days=_m(7.359, "calendar days"), observations=_m(98, "observations (bars, not days)"),
                freshness=_m({"state": "STALE", "age_hours": 13.4})),
        _source("market_neutral_basis", "MARKET_NEUTRAL_BASIS"),
        _source("cash", "TREASURY_CASH", annualized_return=_m(0.0), drawdown=_m(0.0)),
    ]
    by_source = {
        "defi_conservative": {"qualifies": True, "max_paper_weight": 0.5, "blockers": [], "statement": "qualifies"},
        "trading_alpha": {"qualifies": False, "max_paper_weight": 0.0, "statement": "does not qualify",
                          "blockers": ["not allocatable in the ADR-554 contract (research only)",
                                       "cost component maker_fee is UNKNOWN",
                                       "7.4 calendar days < 30 (ADR-590 §4: no annualised figure)",
                                       "trading data is STALE"]},
        "market_neutral_basis": {"qualifies": False, "max_paper_weight": 0.0, "statement": "no",
                                 "blockers": ["gate data_fresh: FAIL (inputs frozen)", "evidence duration NOT_MEASURED"]},
        "cash": {"qualifies": True, "max_paper_weight": 1.0, "blockers": [], "statement": "cash"},
    }
    portfolio = {"basis": "Oracle EVIDENCE_ONLY alternative", "weights": {"defi_conservative": 0.5, "cash": 0.5},
                 "cash": 0.5, "reconstruction": "CAUSAL", "window": {"from": "W-start", "to": "W-end"},
                 "metrics": {"nav": _m(1.0027), "net_return": _m(0.0027), "annualized_return": _m(0.0093),
                             "max_drawdown": _m(-0.00008)}}
    return {"state": "MEASURED", "as_of": "T0-date", "sources": sources,
            "assessment": {"by_source": by_source}, "paper_portfolio": portfolio,
            "correlation_matrix": {"defi_conservative": {"trading_alpha": _nm(state="NOT_ENOUGH_HISTORY")}},
            "frontier": {"answer": "NO", "question": "Can …?", "verdict": "No …"},
            "recommendation_date": "T0-date", "oracle_stance": "INSUFFICIENT_EVIDENCE", "age_hours": 1.0,
            "ledger_chain_ok": True}


def _section(view):
    return {"_meta": {"state": "HEALTHY", "observed_at": AS_OF, "age_min": 60.0, "stale_after_min": 1800},
            "summary": ss.summarize(view)}


def _tl_cell():
    return {"state": "MEASURED", "candidates": 138, "forward": 5, "champions": 0}


# ── absent stays absent (inv. #17) ────────────────────────────────────────────────────────────────────
def test_missing_view_is_not_measured_and_has_no_rows():
    for bad in (None, {}, {"state": "NOT_MEASURED", "reason": "no recommendation"}):
        s = ss.summarize(bad)
        assert s["state"] == "NOT_MEASURED" and "rows" not in s and s["executes"] is False
    assert ss.summarize({"state": "REFUSED", "reason": "paper boundary"})["state"] == "REFUSED"


def test_absent_cells_print_not_measured_never_zero():
    s = ss.summarize(_view())
    basis = next(r for r in s["rows"] if r["source_id"] == "market_neutral_basis")
    assert basis["text"]["ru"]["net"] == "не измерено" and "0" not in basis["text"]["ru"]["net"]
    assert basis["text"]["ru"]["drawdown"] == "не измерено"


def test_refused_portfolio_gives_unknown_weights_not_zero():
    v = _view()
    v["paper_portfolio"] = {"state": "REFUSED", "reason": "immature source got a weight", "basis": "x"}
    s = ss.summarize(v)
    assert s["portfolio"]["state"] == "REFUSED"
    assert all(r["paper_weight"] is None and r["text"]["ru"]["paper_weight"] == "не измерено" for r in s["rows"])


def test_gross_is_never_printed_as_net():
    v = _view()
    ta = next(x for x in v["sources"] if x["source_id"] == "trading_alpha")
    ta["net_return"] = _nm("net not measured")              # only gross is measured now
    row = next(r for r in ss.summarize(v)["rows"] if r["source_id"] == "trading_alpha")
    assert row["text"]["ru"]["net"] == "не измерено"
    assert "0,21" not in row["text"]["ru"]["net"] and "0.21" not in row["text"]["en"]["net"]


def test_stale_source_is_flagged_on_both_surfaces():
    s = ss.summarize(_view())
    ta = s["trading_alpha"]
    assert ta["freshness_state"] == "STALE" and ta["text"]["ru"]["freshness"] == "данные устарели"
    lines = tg.trading_alpha_lines(s, None)
    assert any("данные устарели" in x for x in lines)


# ── the two surfaces show the same truth ───────────────────────────────────────────────────────────────
def test_director_and_telegram_print_the_same_values():
    view = _view()
    card = ct.capital_sources_card(_section(view), _tl_cell())
    s = ss.summarize(view)
    tg_text = "\n".join(tg.sources_lines(s) + tg.trading_alpha_lines(s, None))
    for row in card["rows"]:
        tx = row["text"]["ru"]
        line = next(x for x in tg_text.splitlines() if x.strip().startswith("• " + row["name_ru"] + ":"))
        for key in ("net", "eligibility", "paper_weight"):
            assert tx[key] in line, (row["source_id"], key, tx[key], line)
    ta = card["trading_alpha"]["sleeve"]["text"]["ru"]
    assert "Чистая доходность: " + ta["net"] in tg_text and "Макс. просадка: " + ta["drawdown"] in tg_text
    assert "Доказательства: " + ta["evidence"] in tg_text
    assert card["trading_alpha"]["oracle_eligible"] is False and "Допуск Oracle: НЕТ" in tg_text


def test_calendar_days_and_observations_are_separate():
    ta = ss.summarize(_view())["trading_alpha"]["text"]["ru"]["evidence"]
    assert "7,4 календарных дн." in ta and "98 наблюдений" in ta


# ── never green on UNKNOWN; nothing acts ─────────────────────────────────────────────────────────────────
def test_unmeasured_or_broken_feed_is_never_a_green_card():
    nm = ct.capital_sources_card({"_meta": {"state": "NOT_MEASURED", "reason": "no view"}, "summary":
                                  ss.summarize(None)}, _tl_cell())
    assert nm["state"] == "NOT_MEASURED" and "не измерены" in nm["unknown_ru"]
    broken = ct.capital_sources_card({"_meta": {"state": "CRITICAL", "observed_at": AS_OF}, "summary":
                                      ss.summarize(_view())}, _tl_cell())
    assert broken["state"] == "NOT_MEASURED" and "отозваны" in broken["unknown_ru"]
    stale = ct.capital_sources_card({"_meta": {"state": "STALE", "observed_at": AS_OF, "age_min": 4000,
                                              "stale_after_min": 1800}, "summary": ss.summarize(_view())}, _tl_cell())
    assert stale["state"] == "STALE"


def test_blocker_phrases_are_never_ok_and_unknown_stays_unknown():
    card = ct.capital_sources_card(_section(_view()), _tl_cell())
    tones = [b["tone"] for r in card["rows"] for b in r["blockers_plain"]]
    assert tones and "ok" not in tones
    assert ol.capital_blocker_plain("something nobody wrote yet")["tone"] == "unknown"


def test_lab_counts_unknown_when_the_lab_is_not_measured():
    card = ct.capital_sources_card(_section(_view()), {"state": "STALE", "candidates": 138})
    assert card["trading_alpha"]["research"] is None and card["trading_alpha"]["forward"] is None


def test_card_declares_no_authority():
    card = ct.capital_sources_card(_section(_view()), _tl_cell())
    assert card["executes"] is False and card["real_capital_usd"] == 0


def test_projection_imports_nothing_that_can_act():
    for rel in ("spa_core/investment_cio/sources_summary.py", "spa_core/telegram/views/capital.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module)
            elif isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
        assert not [m for m in mods if "execution" in m or "company_truth" in m], (rel, mods)


# ── owner-language ratchet: every producer template has a Russian phrase ──────────────────────────────
def test_every_cost_component_and_gate_has_a_phrase():
    from spa_core.trading_research import alpha_sleeve
    for comp, state in alpha_sleeve.COST_COMPONENTS.items():
        if state != "KNOWN":
            assert comp in ol.COST_COMPONENT_RU, comp
    gates = set(re.findall(r'"gate":\s*"(\w+)"', (REPO / "spa_core/investment_cio/sleeves.py").read_text(encoding="utf-8")))
    assert gates and gates <= set(ol.GATE_RU), gates - set(ol.GATE_RU)


PRODUCER_TEMPLATES = [
    "not allocatable in the ADR-554 contract (research only)",
    "cost component spread is UNKNOWN",
    "trading data is STALE",
    "2 evidence anomaly(ies) — see anomalies",
    "7.4 calendar days < 30 (ADR-590 §4: no annualised figure)",
    "diversification not measured: 0 of 10 member pairs measured",
    "only 0% of sleeve weight sits in forward-robust (ROBUST+) members (< 50%)",
    "gate data_fresh: FAIL (age 13.91h > 3.0h)",
    "gate stop_not_active: UNKNOWN (stop/kill state not available)",
    "maturity NOT_MEASURED: fewer than 30 valid periods",
    "evidence duration NOT_MEASURED",
    "immature: 7.359 days of evidence < 30",
    "net return not measured (cumulative NOT_MEASURED, annualised STALE) — gross is never used",
    "the return offered as net is labelled gross — refused (Oracle consumes NET return only)",
    "net_return 0.05 exceeds gross_return 0.04 — a gross figure under the net name; refused",
    "annualised net 0.1 exceeds annualised gross 0.05; refused",
    "net return value not numeric",
    "freshness STALE (age 13.91h > 3.0h)",
    "drawdown STALE",
]


def test_every_known_template_has_a_plain_phrase():
    for raw in PRODUCER_TEMPLATES:
        p = ol.capital_blocker_plain(raw)
        assert p["tone"] == "warn" and "неизвестная причина" not in p["text"], raw
        assert not re.search(r"[A-Z_]{4,}", p["text"]), (raw, p["text"])      # no raw codes on the owner layer


def test_every_oracle_stance_has_russian_text():
    from spa_core.investment_cio import contract
    js = (REPO / "spa_core/studio_os/mission_ui/i18n.js").read_text(encoding="utf-8")
    for st in contract.STANCES:
        assert st in tg._STANCE_RU, st
        assert js.count(f'"capital.oracle.stance.{st}"') >= 2, st       # RU and EN


def test_sub_card_badges_follow_their_own_content_not_the_feed():
    """Browser check 07.10: a fresh Oracle view of STALE sources / an UNMEASURED portfolio / an
    unanswered question showed four green «измерено» badges. Each sub-card now carries its own state."""
    card = ct.capital_sources_card(_section(_view()), _tl_cell())       # TA stale in the fixture
    ss_ = card["sub_states"]
    assert ss_["sources"] == "STALE" and ss_["trading_alpha"] == "STALE"
    assert ss_["portfolio"] == "MEASURED" and ss_["research_question"] == "MEASURED"   # answer NO is an answer
    v = _view()
    v["paper_portfolio"]["metrics"]["nav"] = _nm("nothing invested")
    v["frontier"]["answer"] = "UNKNOWN"
    for s in v["sources"]:
        if s["source_id"] == "trading_alpha":
            s["freshness"] = _m({"state": "FRESH"})
    card2 = ct.capital_sources_card(_section(v), _tl_cell())
    assert card2["sub_states"]["portfolio"] == "NOT_MEASURED"
    assert card2["sub_states"]["research_question"] == "NOT_ENOUGH_HISTORY"
    assert card2["sub_states"]["trading_alpha"] == "MEASURED"
    app = (REPO / "spa_core/studio_os/mission_ui/app.js").read_text(encoding="utf-8")
    assert 'subCard("capital.tab.sources", cell, "sources"' in app and "badge_state" in app


# ── review fixes (07.10): definitional cash, view staleness, dates, counts, missing frontier ─────────────
def _cash_definitional_view():
    v = _view()
    for s in v["sources"]:
        if s["source_id"] == "cash":
            s["annualized_return"] = {"value": 0.0, "state": "DEFINITIONAL", "unit": "fraction", "as_of": None,
                                      "note": "no accrual exists for idle cash"}
            s["drawdown"] = {"value": 0.0, "state": "DEFINITIONAL", "unit": "fraction", "as_of": None,
                             "note": "idle cash"}
            s["confidence"] = {"value": "HIGH", "state": "DEFINITIONAL", "unit": None, "as_of": None, "note": "def"}
    return v


def test_cash_zero_is_said_as_definitional_not_as_a_measurement():
    cash = next(r for r in ss.summarize(_cash_definitional_view())["rows"] if r["source_id"] == "cash")
    tx = cash["text"]["ru"]
    assert tx["net"] == "0,00\u00a0% по определению (кэш не начисляет доход)"
    assert "по определению" in tx["drawdown"] and "по определению" in tx["confidence"]
    # positive control: the same zero stamped MEASURED would read as a measured rate
    measured = next(r for r in ss.summarize(_view())["rows"] if r["source_id"] == "cash")
    assert "по определению" not in measured["text"]["ru"]["net"]


def test_producer_emits_cash_as_definitional_and_value_of_refuses_it():
    from spa_core.investment_cio import contract
    c = contract.definitional(0.0, unit="pct_annualized", basis="idle cash")
    assert c["state"] == contract.DEFINITIONAL and contract.value_of(c) is None
    import pytest
    with pytest.raises(ValueError):
        contract.definitional(0.0, unit=None, basis="")


def test_view_staleness_uses_one_constant_on_both_surfaces():
    from spa_core.studio_os import mission_control as mc
    row = next(r for r in mc.CONTRACT if r["path"] == "capital.capital_sources")
    assert row["stale_after_min"] == ss.VIEW_STALE_AFTER_MIN
    v = _view()
    v["age_hours"] = (ss.VIEW_STALE_AFTER_MIN + 60) / 60.0
    s = ss.summarize(v)
    assert s["view_stale"] is True
    assert "УСТАРЕЛО" in "\n".join(tg.sources_lines(s)) and "УСТАРЕЛО" in "\n".join(tg.trading_alpha_lines(s, None))
    v["age_hours"] = 1.0
    s2 = ss.summarize(v)
    assert s2["view_stale"] is False and "УСТАРЕЛО" not in "\n".join(tg.sources_lines(s2))
    v["age_hours"] = None
    assert ss.summarize(v)["view_stale"] is None                    # unknown age is never «fresh»


def test_cumulative_return_names_its_window():
    v = _view()
    for s in v["sources"]:
        if s["source_id"] == "trading_alpha":
            s["evidence_start"] = _m("2026-09-30T21:22:52Z", "iso8601")
            s["measurement_as_of"] = _m("2026-10-08T06:00:00Z", "iso8601")
    ta = ss.summarize(v)["trading_alpha"]["text"]["ru"]["net"]
    assert "с 30.09, на 08.10" in ta and "с начала" not in ta


def test_counts_come_from_the_projection_and_missing_frontier_is_not_measured():
    s = ss.summarize(_view())
    assert s["eligible_count"] == 1 and s["risk_total"] == 3        # conservative of {cons, TA, basis}
    v = _view()
    v.pop("frontier")
    rq = ss.summarize(v)["research_question"]
    assert rq["state"] == "NOT_MEASURED" and rq["answer"] is None
    assert "не измерено" in "\n".join(tg.sources_lines(ss.summarize(v)))


def test_sources_card_is_not_measured_when_no_risk_source_has_a_return():
    v = _view()
    for s in v["sources"]:
        if s["source_type"] != "TREASURY_CASH":
            s["net_return"] = _nm()
            s["annualized_return"] = _nm()
            s["freshness"] = _m({"state": "FRESH"})
    card = ct.capital_sources_card(_section(v), _tl_cell())
    assert card["sub_states"]["sources"] == "NOT_MEASURED"


def test_seam_through_mission_control_build_and_the_real_telegram_screens(tmp_path, monkeypatch):
    """Review P2: the SAME view through mission_control.build → Company Truth card, and through the real
    Telegram screen renderers — values identical, the 300-char safe_text path exercised."""
    from datetime import datetime, timezone
    from spa_core.investment_cio import read as cio_read
    from spa_core.tests import test_mission_control_contract as mcc
    view = _cash_definitional_view()
    for s in view["sources"]:
        if s["source_id"] == "trading_alpha":
            s["evidence_start"] = _m("2026-09-30T21:22:52Z", "iso8601")
            s["measurement_as_of"] = _m("2026-10-08T06:00:00Z", "iso8601")
    view["assessment"]["by_source"]["trading_alpha"]["statement"] = "x" * 900       # long free text
    monkeypatch.setattr(cio_read, "capital_sources", lambda data_dir, now=None: copy.deepcopy(view))
    model = mcc._build(mcc._scene(tmp_path))
    card = model["truth"]["capital"]["sources"]
    assert card["state"] in ("MEASURED", "STALE")
    ta_row = next(r for r in card["rows"] if r["source_id"] == "trading_alpha")
    assert len(ta_row["statement"]) <= 300                            # scrubbed on the Director path
    monkeypatch.setitem(tg.READERS, "data_dir", lambda: tmp_path)
    monkeypatch.setitem(tg.READERS, "now", lambda: datetime(2026, 10, 8, 7, tzinfo=timezone.utc))
    monkeypatch.setitem(tg.READERS, "lab", lambda d: None)
    text, kb = tg._render_menu("ru")
    for row in card["rows"]:
        tx = row["text"]["ru"]
        line = next(x for x in text.splitlines() if x.strip().startswith("• " + row["name_ru"] + ":"))
        # ADR-660 prints «4,89 %» with a NO-BREAK space; the Director path's whitespace
        # normalisation turns it into a plain space. Same visible text — compare it as seen.
        seen = line.replace("\u00a0", " ")
        for key in ("net", "eligibility", "paper_weight"):
            assert tx[key].replace("\u00a0", " ") in seen, (row["source_id"], key)
    assert all(b.get("callback_data", "").startswith("nav:") for r in kb.get("inline_keyboard", []) for b in r)


def test_absent_view_reason_is_plain_russian_on_both_surfaces():
    """Production 07.10: before the first Oracle run with the view, both surfaces printed the English
    reason «the latest recommendation predates the capital-sources view (ADR-641)» inside Russian text."""
    from spa_core.investment_cio import sources_summary as ss
    s = ss.summarize({"state": "NOT_MEASURED",
                      "reason": "the latest recommendation predates the capital-sources view (ADR-641)"})
    assert "следующего ежедневного запуска Oracle" in s["reason_ru"]
    assert "predates" in s["reason"]                         # the technical reason is kept for the details
    assert ss.reason_ru("something new") == "разбор источников недоступен (причина — в технических подробностях)"
