"""ADR-612 — Director OS owner layer: every producer code has a plain-Russian phrase, an unknown
code is never green, and the technical text stays available one tap away.

The vocabularies are ENUMERATED FROM THE PRODUCERS (AST / source), not copied: a producer that
learns a new status/code turns this red until ``owner_language`` says it in words (the ratchet).
And the reverse direction: a phrase for a code no producer emits any more is named too, so the
table cannot rot into a list of ghosts.
"""
from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.studio_os import owner_language as OL
from spa_core.studio_os import readiness_scopes as RS

REPO = Path(__file__).resolve().parents[2]
SNAKE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")


# ── enumerate producers ────────────────────────────────────────────────────────────────────────
def _scope_statuses() -> dict[str, set[str]]:
    """{scope: statuses its builder can return}, read from readiness_scopes.py by AST."""
    tree = ast.parse((REPO / "spa_core/studio_os/readiness_scopes.py").read_text(encoding="utf-8"))
    maps = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    maps[tgt.id] = {v.value for v in node.value.values if isinstance(v, ast.Constant)}
    out: dict[str, set[str]] = {}
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        scope, statuses = None, set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                tup = [e.id for t in node.targets if isinstance(t, ast.Tuple) for e in t.elts if isinstance(e, ast.Name)]
                if names == ["scope"] and isinstance(node.value, ast.Constant):
                    scope = node.value.value
                if "status" in names or (tup and tup[0] == "status"):
                    val = node.value.elts[0] if (tup and isinstance(node.value, ast.Tuple)) else node.value
                    if isinstance(val, ast.Constant):
                        statuses.add(val.value)
                    elif isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute) and \
                            isinstance(val.func.value, ast.Name) and val.func.value.id in maps:
                        statuses |= maps[val.func.value.id]
                        statuses |= {a.value for a in val.args[1:] if isinstance(a, ast.Constant)}
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_item" and len(node.args) > 1 \
                    and isinstance(node.args[1], ast.Constant):
                statuses.add(node.args[1].value)
        if scope:
            out[scope] = statuses
    return out


def _site_codes() -> set[str]:
    src = (REPO / "scripts/site_freshness_monitor.py").read_text(encoding="utf-8")
    return set(re.findall(r'"code":\s*"([A-Z][A-Z_]+)"', src)) | set(re.findall(r'\(\s*"([A-Z][A-Z_]{4,})",', src))


def _integrity_checks() -> set[str]:
    src = (REPO / "spa_core/audit/data_integrity.py").read_text(encoding="utf-8")
    return set(re.findall(r'_safe_check\(\s*check_\w+,\s*"([a-z_]+)"', src))


def _cycle_checks() -> set[str]:
    src = (REPO / "spa_core/monitoring/cycle_health_monitor.py").read_text(encoding="utf-8")
    block = src[src.index("checks = {"):]
    block = block[: block.index("}")]
    return set(re.findall(r'"([a-z_]+)":\s*(?:self\.|[a-z_]+,)', block))


def _system_domains() -> set[str]:
    src = (REPO / "spa_core/monitoring/system_health_monitor.py").read_text(encoding="utf-8")
    block = src[src.index("domain_methods = ["):]
    block = block[: block.index("]")]
    return set(re.findall(r'\("d[^"]*",\s*"([a-z0-9_]+)"', block))


# ── 1. every producer code has a phrase ────────────────────────────────────────────────────────
def test_every_scope_status_a_producer_can_return_has_a_phrase():
    found = _scope_statuses()
    assert set(found) == set(RS.SCOPES), "scope enumeration missed a builder"
    missing = [(sc, st) for sc, sts in found.items() for st in sts
               if st not in OL.GENERIC_STATUS_RU and (sc, st) not in OL.SCOPE_STATUS_RU]
    assert not missing, missing


def test_every_phrased_scope_status_is_still_emitted():
    found = _scope_statuses()
    ghosts = [k for k in OL.SCOPE_STATUS_RU if k[1] not in found.get(k[0], set())]
    assert not ghosts, ghosts


def test_site_codes_both_ways():
    codes = _site_codes()
    assert codes, "site freshness codes not found — enumeration broke"
    assert not codes - set(OL.SITE_CODE_RU), sorted(codes - set(OL.SITE_CODE_RU))
    assert not set(OL.SITE_CODE_RU) - codes, sorted(set(OL.SITE_CODE_RU) - codes)


def test_every_tier1_incident_has_a_phrase():
    from spa_core.telegram.push_policy import TIER1_WHITELIST
    assert not set(TIER1_WHITELIST) - set(OL.INCIDENT_RU), sorted(set(TIER1_WHITELIST) - set(OL.INCIDENT_RU))


def test_every_data_health_check_has_a_phrase():
    checks = _integrity_checks() | _cycle_checks()
    assert {"schema_sanity", "anchor_coverage", "evidence_vs_curve"} <= checks
    assert not checks - set(OL.CHECK_RU), sorted(checks - set(OL.CHECK_RU))


def test_every_system_health_domain_has_a_phrase_both_ways():
    doms = _system_domains()
    assert {"d1_data_pipeline", "d_dfb_defi_board", "d_riskwire"} <= doms, doms
    assert doms == set(OL.SYSTEM_DOMAIN_RU), (sorted(doms ^ set(OL.SYSTEM_DOMAIN_RU)))


def test_daily_report_and_cockpit_share_one_domain_table():
    from spa_core.telegram.reports import daily
    assert daily._DOMAIN_RU is OL.SYSTEM_DOMAIN_RU


def test_problem_families_from_the_store_have_phrases():
    src = (REPO / "spa_core/monitoring/problem_store.py").read_text(encoding="utf-8")
    literal = set(re.findall(r'"cause_code":\s*"([a-z_]+)"', src))
    assert {"retired_but_loaded", "domains_degraded", "publication_behind"} <= literal
    for code in literal:
        assert OL.problem_plain("com.spa.x", code, "")["tone"] != "unknown", code
    assert OL.problem_plain("com.spa.resource_guard", "exit_nonzero:1")["text"] == \
        "агент «resource_guard» завершается с ошибкой (код 1)"
    assert OL.problem_plain("com.spa.x", "stale_log")["tone"] == "warn"


# ── 2. unknown is never green; no tone upgrades ────────────────────────────────────────────────
@pytest.mark.parametrize("fn,args", [
    (OL.scope_plain, ({"scope": "STUDIO_OS_HEALTH", "status": "SOMETHING_NEW"},)),
    (OL.scope_plain, ({"scope": "NEW_SCOPE", "status": "OK"},)),
    (OL.scope_plain, ({"scope": "PUBLICATION_HEALTH", "status": "UNKNOWN", "facts": {"why": "stale"}},)),
    (OL.check_plain, ("anchor_coverage", "NOT_MEASURED")),
    (OL.check_plain, ("anchor_coverage", "WEIRD")),
    (OL.check_plain, ("brand_new_check", "OK")),
    (OL.incident_plain, ("brand_new_event",)),
    (OL.problem_plain, ("com.spa.x", "some_new_cause", "detail")),
])
def test_unknown_inputs_are_never_ok(fn, args):
    out = fn(*args)
    assert out["tone"] in ("unknown", "warn", "alert") and out["tone"] != "ok", out
    assert out["text"]


def test_ok_tone_only_where_the_producer_said_ok():
    for (scope, status), (tone, _text) in OL.SCOPE_STATUS_RU.items():
        if tone == "ok":
            assert status in ("OK", "READY"), (scope, status)
    for status, (tone, _t) in OL.GENERIC_STATUS_RU.items():
        assert tone != "ok", status


def test_owner_examples_from_the_epic():
    assert OL.check_plain("anchor_coverage", "UNCHECKED")["text"] == \
        "не проверено, что журнал можно восстановить из внешней контрольной точки"
    assert "система не считает их готовыми" in OL.scope_plain(
        {"scope": "PRODUCT_DATA_HEALTH", "status": "CRITICAL", "facts": {}})["text"]


# ── 3. the owner layer carries no codes ─────────────────────────────────────────────────────────
def _all_phrases():
    yield from (t for _tone, t in OL.SCOPE_STATUS_RU.values())
    yield from (t for _tone, t in OL.GENERIC_STATUS_RU.values())
    yield from OL.WHY_RU.values()
    yield from OL.LIVE_BLOCKER_RU.values()
    yield from OL.CHECK_RU.values()
    yield from OL.SITE_CODE_RU.values()
    yield from (t for _tone, t in OL.INCIDENT_RU.values())
    yield from OL.SYSTEM_DOMAIN_RU.values()


def test_phrases_have_no_snake_case_codes():
    bad = [p for p in _all_phrases() if SNAKE.search(p)]
    assert not bad, bad


def test_scope_plain_on_real_shapes_reads_like_a_sentence():
    inv = OL.scope_plain({"scope": "INVESTMENT_ENGINE_READINESS", "status": "NOT_READY",
                          "facts": {"live_blockers": ["custody/MPC not connected", "external audit pending",
                                                      "SPA_EXECUTION_MODE not enabled"],
                                    "open_owner_gates": ["custody", "audit", "legal"]}})
    assert "ready_for_live" not in inv["text"] and "Ваших решений открыто: 3" in inv["text"]
    prod = OL.scope_plain({"scope": "PRODUCT_DATA_HEALTH", "status": "WARN",
                           "facts": {"evidence_vs_curve": "WARNING", "divergent_days": 19, "compared_days": 89,
                                     "artifact_integrity": "HEALTHY"}})
    assert "19 из 89" in prod["text"] and "evidence_vs_curve" not in prod["text"]
    assert not SNAKE.search(inv["text"]) and not SNAKE.search(prod["text"])


# ── 4. the model carries both layers, and the producer's facts reach it ─────────────────────────
def test_every_readiness_item_carries_facts(tmp_path):
    items = RS.scoped_readiness(tmp_path / "data", now=datetime(2026, 10, 7, tzinfo=timezone.utc))  # FROZEN-DATE-OK: injected-clock — scoped_readiness(now=)
    assert len(items) == 6
    for it in items:
        assert isinstance(it.get("facts"), dict), it["scope"]
        assert it["status"] == "UNKNOWN" and it["facts"].get("why") == "missing", it


def test_company_truth_scopes_problems_incidents_have_plain_and_keep_evidence(tmp_path):
    from spa_core.studio_os import company_truth as CT
    now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — studio_incidents(now=)
    sc = CT._sanitize_scope({"scope": "PRODUCT_DATA_HEALTH", "status": "WARN", "reason": "overall=WARNING; evidence_vs_curve=WARNING",
                             "blocking_effect": "x. y", "facts": {"divergent_days": 1, "compared_days": 2}})
    assert sc["plain_ru"] and sc["reason_ru"].startswith("overall=")          # both layers
    inc = CT.studio_incidents({"_meta": {"state": "HEALTHY"},
                               "open": [{"event": "resource_critical", "since": "2026-10-07T10:00:00+00:00"}]}, now)
    it = inc["items"][0]
    assert it["plain_ru"] == "на Маке почти закончились диск или память" and it["title_ru"] == "resource_critical"
    assert it["since_plain_ru"] == "2 ч назад"


def test_ui_renders_plain_first_and_keeps_tech_details():
    app = (REPO / "spa_core/studio_os/mission_ui/app.js").read_text(encoding="utf-8")
    i18n = (REPO / "spa_core/studio_os/mission_ui/i18n.js").read_text(encoding="utf-8")
    assert app.count("it.plain_ru") >= 2 and "s.plain_ru" in app and "techDetails(" in app
    assert i18n.count('"common.tech_details"') == 2           # ru + en
    # an unknown tone never gets the ok colour
    assert 'tone === "ok" || tone === "warn" || tone === "alert" ? tone : "unknown"' in app


def test_scopes_are_judged_at_read_time_not_at_build_start(tmp_path, monkeypatch):
    """Replays the prod defect 06–07.10: every bundle showed OWNER_CONTROL_HEALTH=DEGRADED with a
    beacon −205…−280 s «in the future», because the build pinned `now` at its START and ran for
    minutes. Positive control: a step before the scopes is slowed down; the scopes must still see
    a clock taken after it (an injected clock, by contrast, is kept as given)."""
    import time
    from datetime import timedelta
    from spa_core.studio_os import mission_control as MC
    from spa_core.studio_os import readiness_scopes as rs_mod
    seen = {}

    def slow_cards(tdir):
        time.sleep(1.5)
        return None

    def capture(data, now=None):
        seen["now"] = now
        return []

    monkeypatch.setattr(MC, "_cards", slow_cards)
    monkeypatch.setattr(rs_mod, "scoped_readiness", capture)
    (tmp_path / "data").mkdir()
    start = datetime.now(timezone.utc)
    MC.build(MC.MCInputs(repo=tmp_path, mirror=tmp_path, measure_host=False, collect=lambda: {},
                         packages=lambda: None, git_log=lambda n: [], leases=lambda: [],
                         launchctl_full=lambda: ""))
    assert seen["now"] - start >= timedelta(seconds=1.4), (start, seen["now"])
    fixed = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — MCInputs(now=)
    MC.build(MC.MCInputs(repo=tmp_path, mirror=tmp_path, now=fixed, measure_host=False, collect=lambda: {},
                         packages=lambda: None, git_log=lambda n: [], leases=lambda: [],
                         launchctl_full=lambda: ""))
    assert seen["now"] == fixed


def test_owner_control_ok_phrase_does_not_claim_buttons_work():
    ok = OL.scope_plain({"scope": "OWNER_CONTROL_HEALTH", "status": "OK",
                         "facts": {"beacon_age_s": 12, "beacon_max_age_s": 300}})["text"]
    assert "кнопки и команды работают" not in ok and "проверяется отдельно" in ok and "5 мин" in ok
    # the scope really uses the 300-s liveness threshold, not the 6-h buttons one
    from spa_core.monitoring.telegram_health import BEACON_MAX_AGE_S
    assert RS._TG_BEACON_MAX_AGE_S == BEACON_MAX_AGE_S == 300


def test_readiness_wording_says_met_or_not_met():
    assert "выполнены" in OL.SCOPE_STATUS_RU[("INVESTMENT_ENGINE_READINESS", "READY")][1]
    assert "не выполнены" in OL.SCOPE_STATUS_RU[("INVESTMENT_ENGINE_READINESS", "NOT_READY")][1]
    assert not any("закрыт" in t for _tone, t in OL.SCOPE_STATUS_RU.values())
