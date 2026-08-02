"""
Tests for spa_core.analytics.signal_aggregator (audit 2026-08-02).

Covers the protocol-blind-constant fix:
* no-arg fallback removed — a module that cannot accept the protocol context
  is UNCHECKED, its built-in demo data never becomes a score;
* failures are loud — unchecked/failed/dormant statuses land in the health
  log and in _meta.module_status of the output JSON;
* the adapter's except no longer swallows the diagnosis (failed + detail);
* _coerce_score no longer accepts a generic {"value": ...} dict or bools.
"""
from __future__ import annotations

import sys
import types

import pytest

from spa_core.analytics import signal_aggregator as sa


# ─── helpers ─────────────────────────────────────────────────────────────────

_FAKE_PREFIX = "_fake_test_mod_"


def _install_fake_module(name: str, **funcs):
    """Register a synthetic module as spa_core.analytics.<name>."""
    full = "spa_core.analytics." + name
    mod = types.ModuleType(full)
    for fname, fn in funcs.items():
        setattr(mod, fname, fn)
    sys.modules[full] = mod
    return {"module": name, "class": None, "tier": "B",
            "category": "test", "weight": 0.5, "protocols": ["all"]}


@pytest.fixture(autouse=True)
def _cleanup_fake_modules():
    yield
    for key in [k for k in sys.modules
                if k.startswith("spa_core.analytics." + _FAKE_PREFIX)]:
        del sys.modules[key]


# ─── _coerce_score tightening ────────────────────────────────────────────────

def test_coerce_rejects_generic_value_key():
    # {"value": ...} could be APY/TVL/anything — no longer coerced to risk
    assert sa._ModuleAdapter._coerce_score({"value": 42.0}) is None


def test_coerce_rejects_bool_score():
    assert sa._ModuleAdapter._coerce_score({"score": True}) is None
    assert sa._ModuleAdapter._coerce_score({"custom_score": True}) is None


def test_coerce_still_accepts_semantic_risk_keys():
    assert sa._ModuleAdapter._coerce_score({"risk_score": 55.0}) == 55.0
    assert sa._ModuleAdapter._coerce_score({"depeg_probability": 0.4}) == 40.0
    assert sa._ModuleAdapter._coerce_score({"risk": 0.7}) == 70.0
    assert sa._ModuleAdapter._coerce_score({"slashing_risk_score": 33.0}) == 33.0
    assert sa._ModuleAdapter._coerce_score({"risk_label": "HIGH"}) == 78.0


# ─── adapter: no-arg fallback removed ────────────────────────────────────────

def test_no_arg_only_module_is_unchecked():
    """A module whose entrypoints take no arguments never sees the protocol —
    it must come back UNCHECKED, not silently score its demo data."""
    info = _install_fake_module(
        _FAKE_PREFIX + "noarg",
        analyze=lambda: {"risk_score": 67.0},  # would be the blind constant
    )
    adapter = sa._ModuleAdapter(info)
    score, status, detail = adapter.run("aave_v3", {})
    assert score is None
    assert status == "unchecked"
    assert "entrypoint" in detail


def test_context_module_receives_protocol():
    """Context-accepting module gets ctx['protocol'] → per-protocol scores differ."""
    info = _install_fake_module(
        _FAKE_PREFIX + "ctx",
        analyze=lambda context: {
            "risk_score": 80.0 if context["protocol"] == "aave_v3" else 20.0
        },
    )
    adapter = sa._ModuleAdapter(info)
    s1, st1, _ = adapter.run("aave_v3", {})
    s2, st2, _ = adapter.run("maple", {})
    assert (st1, st2) == ("ok", "ok")
    assert s1 == 80.0 and s2 == 20.0


def test_exception_is_failed_with_detail():
    def boom(context):
        raise ValueError("feed corrupt")
    info = _install_fake_module(_FAKE_PREFIX + "boom", analyze=boom)
    score, status, detail = sa._ModuleAdapter(info).run("aave_v3", {})
    assert score is None
    assert status == "failed"
    assert "ValueError" in detail and "feed corrupt" in detail


def test_internal_typeerror_not_swallowed():
    """TypeError raised INSIDE a compatible entrypoint must surface as failed,
    not be mistaken for a signature mismatch."""
    def analyze(context):
        raise TypeError("inner bug")
    info = _install_fake_module(_FAKE_PREFIX + "innertype", analyze=analyze)
    score, status, detail = sa._ModuleAdapter(info).run("aave_v3", {})
    assert status == "failed"
    assert "TypeError" in detail


def test_uncoercible_result_is_dormant():
    info = _install_fake_module(
        _FAKE_PREFIX + "dormant",
        analyze=lambda context: {"value": 42.0},  # generic dict → no score
    )
    score, status, detail = sa._ModuleAdapter(info).run("aave_v3", {})
    assert score is None
    assert status == "dormant"


# ─── aggregator: loud statuses in output ─────────────────────────────────────

def test_tier_b_module_status_in_meta(tmp_path, monkeypatch):
    infos = [
        _install_fake_module(
            _FAKE_PREFIX + "good",
            analyze=lambda context: {"risk_score": 60.0},
        ),
        _install_fake_module(
            _FAKE_PREFIX + "blind",
            analyze=lambda: {"risk_score": 99.0},
        ),
        _install_fake_module(
            _FAKE_PREFIX + "broken",
            analyze=lambda context: (_ for _ in ()).throw(RuntimeError("x")),
        ),
    ]
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)

    agg = sa.SignalAggregator(data_dir=tmp_path)
    out = agg.run_tier_b(["aave_v3", "maple"], {})

    ms = out["_meta"]["module_status"]
    assert ms["counts"] == {"ok": 1, "unchecked": 1, "failed": 1}
    assert ms["not_ok"]["unchecked"] == [_FAKE_PREFIX + "blind"]
    assert ms["not_ok"]["failed"] == [_FAKE_PREFIX + "broken"]

    # confidence counts only genuinely-ok modules (1 of 3)
    for proto in ("aave_v3", "maple"):
        sig = out["protocols"][proto]
        assert sig["modules_ok"] == 1
        assert sig["confidence"] == pytest.approx(1 / 3, abs=1e-4)

    # health log carries the loud statuses
    statuses = {(e["module"], e["status"]) for e in agg._log}
    assert (_FAKE_PREFIX + "blind", "unchecked") in statuses
    assert (_FAKE_PREFIX + "broken", "failed") in statuses


def test_tier_b_blind_markup_excluded(tmp_path, monkeypatch):
    """Modules in PROTOCOL_BLIND_MODULES are not executed: loud "blind" status,
    excluded from composite AND from the confidence numerator."""
    executed = []

    def _blind_analyze(context):
        executed.append(context["protocol"])
        return {"risk_score": 5.0}  # would fake-boost the multiplier

    infos = [
        _install_fake_module(
            _FAKE_PREFIX + "live",
            analyze=lambda context: {"risk_score": 60.0},
        ),
        _install_fake_module(_FAKE_PREFIX + "const", analyze=_blind_analyze),
    ]
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)
    monkeypatch.setattr(sa, "PROTOCOL_BLIND_MODULES",
                        frozenset({_FAKE_PREFIX + "const"}))

    agg = sa.SignalAggregator(data_dir=tmp_path)
    out = agg.run_tier_b(["aave_v3"], {})

    assert executed == []  # blind module never ran
    ms = out["_meta"]["module_status"]
    assert ms["counts"] == {"ok": 1, "blind": 1}
    assert ms["not_ok"]["blind"] == [_FAKE_PREFIX + "const"]

    sig = out["protocols"]["aave_v3"]
    assert sig["modules_ok"] == 1
    assert sig["confidence"] == pytest.approx(0.5, abs=1e-4)
    # composite reflects only the live module (60), not blended with 5.0
    assert sig["composite_risk_0_100"] == pytest.approx(60.0)
    assert (_FAKE_PREFIX + "const", "blind") in {
        (e["module"], e["status"]) for e in agg._log
    }


def test_all_blind_registry_goes_neutral(tmp_path, monkeypatch):
    """If every module is protocol-blind (today's real state), Tier-B honestly
    reports UNKNOWN: neutral multiplier 1.0, confidence 0 — instead of the
    pre-fix constant composite ≈8.6 → fake 1.41x boost for every protocol."""
    infos = [_install_fake_module(
        _FAKE_PREFIX + "c" + str(i),
        analyze=(lambda i: lambda context: {"risk_score": float(i)})(i),
    ) for i in range(3)]
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)
    monkeypatch.setattr(sa, "PROTOCOL_BLIND_MODULES",
                        frozenset(m["module"] for m in infos))

    out = sa.SignalAggregator(data_dir=tmp_path).run_tier_b(
        ["aave_v3", "maple"], {})
    for proto in ("aave_v3", "maple"):
        sig = out["protocols"][proto]
        assert sig["risk_multiplier"] == 1.0
        assert sig["confidence"] == 0.0
        assert sig["composite_risk_0_100"] == 50.0
        assert sig["modules_ok"] == 0


def test_real_markup_matches_registry():
    """Every marked-blind module must exist in the Tier-B registry — guards
    against markup drifting after registry renames."""
    from spa_core.analytics._protocol_blindness import PROTOCOL_BLIND_MODULES
    tier_b = {m["module"] for m in sa.registry.get_tier_modules("B")}
    missing = PROTOCOL_BLIND_MODULES - tier_b
    assert missing == set(), f"markup names not in Tier-B registry: {sorted(missing)[:5]}"


def test_tier_b_not_protocol_blind(tmp_path, monkeypatch):
    """The core audit claim: identical composite for every protocol is gone
    when a context-aware module differentiates them."""
    infos = [_install_fake_module(
        _FAKE_PREFIX + "differ",
        analyze=lambda context: {
            "risk_score": 90.0 if context["protocol"] == "aave_v3" else 10.0
        },
    )]
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda tier: infos)

    out = sa.SignalAggregator(data_dir=tmp_path).run_tier_b(
        ["aave_v3", "maple"], {})
    a = out["protocols"]["aave_v3"]
    m = out["protocols"]["maple"]
    assert a["composite_risk_0_100"] != m["composite_risk_0_100"]
    assert a["risk_multiplier"] != m["risk_multiplier"]
