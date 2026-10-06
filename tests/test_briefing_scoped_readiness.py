"""test_briefing_scoped_readiness.py — ADR-580 §C3 (RM-TRUTH-01, workstream W6).

The briefing used to print one headline: "GoLive ✅ 29/29 pass — READY" straight from
`golive_status.json`'s inventory count, while the real gate (`execution_readiness.json
.ready_for_live`) said False for weeks (ADR-530 / REVIEW_1 §3). These tests pin two
contracts on the FIXED briefing:

  1. The investment-readiness line can never say READY while `ready_for_live` is false
     (and, as a positive control, the inventory count no longer decides this — a healthy
     inventory next to a false gate must still print NOT_READY/UNKNOWN, never READY).
  2. Scope independence survives all the way to the rendered text: an agent-fleet CRITICAL
     does not move the investment-readiness line, and a NOT_READY investment gate does not
     move the agent-fleet line. One rollup overwriting another is exactly the bug the
     six-scope design (`spa_core.studio_os.readiness_scopes`) replaces.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import update_system_briefing as usb

NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)


def _scope(scope, status, reason="", blocking_effect="", as_of=None, source="", freshness=None):
    return {
        "scope": scope,
        "status": status,
        "as_of": as_of,
        "source": source,
        "freshness": freshness or {"age_hours": 0.1, "stale_after_hours": 26.0,
                                    "threshold_source": "declared:manifest", "stale": False},
        "blocking_effect": blocking_effect or "test blocking effect",
        "reason": reason or f"{scope} test reason",
    }


def _all_scopes(investment_status, agent_status="OK", **extra_reasons):
    """A full 6-scope list with ONE scope overridden for the test under it."""
    return [
        _scope("INVESTMENT_ENGINE_READINESS", investment_status,
               reason=extra_reasons.get("investment_reason", "ready_for_live=false")),
        _scope("STUDIO_OS_HEALTH", agent_status,
               reason=extra_reasons.get("agent_reason", "overall_status=OK: 89/89 OK")),
        _scope("PRODUCT_DATA_HEALTH", "OK"),
        _scope("PUBLICATION_HEALTH", "OK"),
        _scope("OWNER_CONTROL_HEALTH", "OK"),
        _scope("PUBLIC_SURFACE", "OK"),
    ]


def _patch_scoped(monkeypatch, scopes):
    monkeypatch.setattr(usb, "scoped_readiness", lambda data_dir: scopes)


def _patch_golive_status(monkeypatch, payload):
    def fake_read_json(name):
        return payload if name == "golive_status.json" else {}
    monkeypatch.setattr(usb, "read_json", fake_read_json)


# ---------------------------------------------------------------------------
# 1. Never READY while ready_for_live is false — even with a clean 29/29 inventory
# ---------------------------------------------------------------------------
def test_not_ready_investment_never_prints_ready(monkeypatch):
    _patch_scoped(monkeypatch, _all_scopes("NOT_READY"))
    _patch_golive_status(monkeypatch, {"passed": 29, "total": 29})
    text = usb.build_golive_section()
    assert "NOT_READY" in text
    assert "⛔" in text
    # The inventory count still appears, but must never be read as the verdict.
    assert "29/29" in text
    assert "READY" not in text.replace("NOT_READY", "").replace("ALREADY", "")


def test_unknown_investment_never_prints_ready_either(monkeypatch):
    """A missing/stale execution_readiness.json must say UNKNOWN, not fall back to READY."""
    _patch_scoped(monkeypatch, _all_scopes("UNKNOWN", investment_reason="execution_readiness.json отсутствует"))
    _patch_golive_status(monkeypatch, {"passed": 29, "total": 29})
    text = usb.build_golive_section()
    assert "UNKNOWN" in text
    assert "READY" not in text.replace("NOT_READY", "").replace("ALREADY", "")


def test_ready_only_prints_when_the_scope_itself_says_ready(monkeypatch):
    """Positive control: READY is reachable, and only from the scope's own verdict."""
    _patch_scoped(monkeypatch, _all_scopes("READY", investment_reason="ready_for_live=true"))
    _patch_golive_status(monkeypatch, {"passed": 29, "total": 29})
    text = usb.build_golive_section()
    assert "READY" in text
    assert "✅" in text


# ---------------------------------------------------------------------------
# 2. Scope independence survives rendering
# ---------------------------------------------------------------------------
def test_agent_critical_does_not_move_the_investment_line(monkeypatch):
    scopes = _all_scopes("READY", agent_status="CRITICAL",
                          agent_reason="overall_status=CRITICAL: 84/89 OK, critical=1")
    _patch_scoped(monkeypatch, scopes)
    _patch_golive_status(monkeypatch, {"passed": 29, "total": 29})
    text = usb.build_golive_section()
    assert "**Готовность к live (инвестиции): ✅ READY**" in text
    assert "| STUDIO_OS_HEALTH | ⛔ CRITICAL |" in text


def test_investment_not_ready_does_not_move_the_agent_line(monkeypatch):
    scopes = _all_scopes("NOT_READY", agent_status="OK")
    _patch_scoped(monkeypatch, scopes)
    _patch_golive_status(monkeypatch, {"passed": 29, "total": 29})
    text = usb.build_golive_section()
    assert "**Готовность к live (инвестиции): ⛔ NOT_READY**" in text
    assert "| STUDIO_OS_HEALTH | ✅ OK |" in text


# ---------------------------------------------------------------------------
# 3. No aggregate: all six scopes are visible, and nowhere is there a 7th "overall" row
# ---------------------------------------------------------------------------
def test_all_six_scopes_appear_and_no_rollup_row(monkeypatch):
    scopes = _all_scopes("NOT_READY")
    _patch_scoped(monkeypatch, scopes)
    _patch_golive_status(monkeypatch, {"passed": 27, "total": 29})
    text = usb.build_golive_section()
    for s in scopes:
        assert s["scope"] in text
    assert "overall" not in text.lower()
    assert "OVERALL" not in text


# ---------------------------------------------------------------------------
# 4. A broken scope module must not take the whole briefing down with it
# ---------------------------------------------------------------------------
def test_scoped_readiness_exception_is_reported_not_raised(monkeypatch):
    def boom(data_dir):
        raise RuntimeError("scope module is broken")
    monkeypatch.setattr(usb, "scoped_readiness", boom)
    _patch_golive_status(monkeypatch, {"passed": 29, "total": 29})
    text = usb.build_golive_section()
    assert "не измерено" in text
    assert "RuntimeError" in text


# ---------------------------------------------------------------------------
# 5. End-to-end, with the REAL scoped_readiness (no monkeypatch) against real files
# ---------------------------------------------------------------------------
def test_end_to_end_real_scoped_readiness_against_tmp_data_dir(monkeypatch, tmp_path):
    """Drives the actual spa_core.studio_os.readiness_scopes computation (not a double),
    the same way the production DATA_DIR would be read, with a false ready_for_live and a
    healthy inventory — the exact shape of the ADR-530 finding."""
    # build_golive_section() calls the real scoped_readiness() with no `now=` override, so
    # it judges freshness against the REAL wall clock here — timestamps must be real-"now"
    # relative, not the fixture NOW used by the other (monkeypatched-scope) tests above.
    real_now = datetime.now(timezone.utc)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "execution_readiness.json").write_text(json.dumps({
        "audited_at": (real_now - timedelta(minutes=5)).isoformat(),
        "ready_for_live": False,
        "live_blockers": ["custody/MPC not connected", "external audit pending"],
    }), encoding="utf-8")
    (data_dir / "owner_blockers.json").write_text(json.dumps({
        "generated_at": (real_now - timedelta(minutes=5)).isoformat(), "gates": [],
    }), encoding="utf-8")
    golive_status = {"passed": 29, "total": 29, "ready": True}
    (data_dir / "golive_status.json").write_text(json.dumps(golive_status), encoding="utf-8")

    monkeypatch.setattr(usb, "DATA_DIR", str(data_dir))

    def fake_read_json(name):
        path = data_dir / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}
    monkeypatch.setattr(usb, "read_json", fake_read_json)

    text = usb.build_golive_section()
    assert "NOT_READY" in text
    assert "29/29" in text
    assert "READY" not in text.replace("NOT_READY", "").replace("ALREADY", "")
