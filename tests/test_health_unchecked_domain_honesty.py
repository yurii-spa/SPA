"""A health domain that was never measured must NEVER read as healthy.

Observed defect (data/system_health.json, run 20260729T0600):

    "d2_connectivity": {"status": "OK", "ms": 158971}

The domain blew its 20s budget, so its only result was a single SKIPPED
`d2.budget` sentinel. `_worst()` excludes SKIPPED from the roll-up and falls back
to OK for an empty list, so the domain was published as **OK** — and
`update_system_briefing.build_system_health_section()` lists only domains whose
status is not in ("OK", "INFO"), so the owner-facing briefing hid the fact that
connectivity had not been checked at all. Fail-OPEN, against invariant #2
(refusal-first: unknown ⇒ refuse/flag, never assume healthy).

Second defect on the same line: the budget bounded nothing. `with
ThreadPoolExecutor(...)` joins its worker on __exit__, so the run paid the full
unbounded cost (159s against a 20s budget) *and* threw the completed answer away.

These tests are hermetic — no network, no subprocess, no real data/.
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import pytest

import update_system_briefing as usb
from spa_core.monitoring import system_health_monitor as shm
from spa_core.monitoring.system_health_monitor import (
    CheckResult, SystemHealthMonitor, OK, WARNING, SKIPPED,
)


# ---------------------------------------------------------------------------
# Fixtures — a monitor over an empty tmp data dir. Domain results are patched
# per-test, so the on-disk contents never matter.
# ---------------------------------------------------------------------------
@pytest.fixture
def mon(tmp_path):
    (tmp_path / "data").mkdir()
    m = SystemHealthMonitor(data_dir=str(tmp_path / "data"), project_root=str(tmp_path))
    return m


def _silence_domains(monkeypatch, mon, keep=()):
    """Make every domain except `keep` return one cheap OK check."""
    for short, attr in (("d1", "check_d1_data_pipeline"),
                        ("d2", "check_d2_connectivity"),
                        ("d3", "check_d3_strategy_quality"),
                        ("d4", "check_d4_external"),
                        ("d5", "check_d5_code_integrity"),
                        ("d6", "check_d6_risk_gates"),
                        ("d7", "check_d7_hygiene"),
                        ("d_dfb", "check_d_dfb_defi_board"),
                        ("d_riskwire", "check_d_riskwire")):
        if short in keep:
            continue
        dname = attr.replace("check_", "")
        monkeypatch.setattr(mon, attr,
                            (lambda _s=short, _d=dname:
                             [CheckResult(f"{_s}.stub", _d, OK, "stub ok")]))
    monkeypatch.setattr(mon, "_prelude", lambda: None)
    monkeypatch.setattr(mon, "_load_previous", lambda: None)


# ---------------------------------------------------------------------------
# 1. Budget timeout ⇒ the domain is WARNING + flagged unchecked, never OK
# ---------------------------------------------------------------------------
def test_domain_over_budget_is_not_reported_ok(mon, monkeypatch):
    _silence_domains(monkeypatch, mon, keep=("d2",))
    monkeypatch.setitem(shm._DOMAIN_BUDGET, "d2", 0.2)

    def slow():
        time.sleep(3.0)
        return [CheckResult("d2.defillama.reach", "d2_connectivity", OK, "reachable")]

    monkeypatch.setattr(mon, "check_d2_connectivity", slow)

    report = mon.collect()
    d2 = report["domains"]["d2_connectivity"]
    assert d2["status"] == WARNING, "a domain that ran zero checks must not read OK"
    assert d2["unchecked"] is True

    budget_check = [c for c in report["checks"] if c["id"] == "d2.budget"]
    assert len(budget_check) == 1
    # WARNING, not SKIPPED: SKIPPED is excluded from every roll-up, which is
    # exactly how "never measured" became "healthy".
    assert budget_check[0]["status"] == WARNING
    assert "NOT CHECKED" in budget_check[0]["title"]


def test_domain_over_budget_degrades_overall_status(mon, monkeypatch):
    """With every other domain green, the run must still not report OK."""
    _silence_domains(monkeypatch, mon, keep=("d2",))
    monkeypatch.setitem(shm._DOMAIN_BUDGET, "d2", 0.2)
    monkeypatch.setattr(mon, "check_d2_connectivity",
                        lambda: (time.sleep(3.0), [])[1])

    report = mon.collect()
    assert report["overall_status"] == WARNING
    assert report["counts"][WARNING] >= 1


# ---------------------------------------------------------------------------
# 2. The budget must actually bound wall-clock
# ---------------------------------------------------------------------------
def test_budget_bounds_wall_clock(mon, monkeypatch):
    """The timed-out worker is abandoned, not joined.

    Before the fix `with ThreadPoolExecutor(...)` joined the straggler on
    __exit__, so a 0.2s budget still cost the full 5s (observed in prod: 20s
    budget, 158_971ms spent). Generous ceiling (3s) so the assertion is about
    "does not wait for the worker", not about machine speed.
    """
    _silence_domains(monkeypatch, mon, keep=("d2",))
    monkeypatch.setitem(shm._DOMAIN_BUDGET, "d2", 0.2)
    monkeypatch.setattr(mon, "check_d2_connectivity",
                        lambda: (time.sleep(5.0), [])[1])

    t0 = time.monotonic()
    mon.collect()
    elapsed = time.monotonic() - t0
    assert elapsed < 3.0, f"budget did not bound the run: {elapsed:.1f}s"


# ---------------------------------------------------------------------------
# 3. All-SKIPPED domain (no timeout involved) is unknown, not healthy
# ---------------------------------------------------------------------------
def test_all_skipped_domain_is_unchecked(mon, monkeypatch):
    _silence_domains(monkeypatch, mon, keep=("d3",))
    monkeypatch.setattr(mon, "check_d3_strategy_quality", lambda: [
        CheckResult("d3.cycle.ran_today", "d3_strategy_quality", SKIPPED,
                    skipped_reason="upstream equity load failed"),
        CheckResult("d3.equity.trend7", "d3_strategy_quality", SKIPPED,
                    skipped_reason="upstream equity load failed"),
    ])

    report = mon.collect()
    d3 = report["domains"]["d3_strategy_quality"]
    assert d3["status"] == WARNING
    assert d3["unchecked"] is True


def test_run_with_zero_real_checks_is_not_ok(mon, monkeypatch):
    """Nothing measured anywhere ⇒ the run is unknown, never OK."""
    _silence_domains(monkeypatch, mon)
    for attr, dname in (("check_d1_data_pipeline", "d1_data_pipeline"),
                        ("check_d2_connectivity", "d2_connectivity"),
                        ("check_d3_strategy_quality", "d3_strategy_quality"),
                        ("check_d4_external", "d4_external"),
                        ("check_d5_code_integrity", "d5_code_integrity"),
                        ("check_d6_risk_gates", "d6_risk_gates"),
                        ("check_d7_hygiene", "d7_hygiene"),
                        ("check_d_dfb_defi_board", "d_dfb_defi_board"),
                        ("check_d_riskwire", "d_riskwire")):
        monkeypatch.setattr(mon, attr, (lambda _d=dname: [
            CheckResult(f"{_d}.x", _d, SKIPPED, skipped_reason="no data")]))

    report = mon.collect()
    assert report["overall_status"] == WARNING
    assert all(d.get("unchecked") is True for d in report["domains"].values())


# ---------------------------------------------------------------------------
# 4. A healthy domain keeps reading healthy (no false alarm introduced)
# ---------------------------------------------------------------------------
def test_healthy_domains_still_ok(mon, monkeypatch):
    _silence_domains(monkeypatch, mon)
    report = mon.collect()
    assert report["overall_status"] == OK
    for name, d in report["domains"].items():
        assert d["status"] == OK, name
        assert "unchecked" not in d


# ---------------------------------------------------------------------------
# 5. The owner-facing briefing surfaces the unchecked domain in words
# ---------------------------------------------------------------------------
def _briefing_with_domains(monkeypatch, domains, overall="WARNING"):
    def fake_read_json(name):
        if name == "system_health.json":
            return {
                "overall_status": overall,
                "counts": {"OK": 34, "WARNING": 1, "CRITICAL": 0},
                "generated_at": (date.today() - timedelta(days=0)).isoformat() + "T06:00:00",
                "domains": domains,
            }
        return {}
    monkeypatch.setattr(usb, "read_json", fake_read_json)
    return usb.build_system_health_section()


def test_briefing_marks_unchecked_domain(monkeypatch):
    text = _briefing_with_domains(monkeypatch, {
        "d2_connectivity": {"status": WARNING, "ms": 158971, "unchecked": True},
        "d5_code_integrity": {"status": OK, "ms": 208},
    })
    assert "d2_connectivity" in text, "unchecked domain must appear in Problem domains"
    assert "NOT CHECKED" in text


def test_briefing_does_not_mislabel_measured_warning(monkeypatch):
    """A real measured WARNING must not be described as 'not checked'."""
    text = _briefing_with_domains(monkeypatch, {
        "d1_data_pipeline": {"status": WARNING, "ms": 4},
    })
    assert "d1_data_pipeline" in text
    assert "NOT CHECKED" not in text


# ---------------------------------------------------------------------------
# 6. The Telegram System screen says it in words, in both languages
# ---------------------------------------------------------------------------
def _system_screen(monkeypatch, domains, lang):
    from spa_core.telegram.views import _base as B
    from spa_core.telegram.views import health as hv

    def fake_read_json(name, default=None):
        if name == "system_health.json":
            return {"overall_status": WARNING,
                    "counts": {"CRITICAL": 0, "WARNING": 1, "INFO": 0, "OK": 34},
                    "run_id": "20260729T0600", "fingerprint": "abc123",
                    "domains": domains}
        return default if default is not None else {}

    monkeypatch.setattr(B, "read_json", fake_read_json)
    text, _ = hv.render_system(lang=lang)
    return text


@pytest.mark.parametrize("lang,word", [("en", "not checked"), ("ru", "не проверялся")])
def test_telegram_system_screen_marks_unchecked(monkeypatch, lang, word):
    text = _system_screen(monkeypatch, {
        "d2_connectivity": {"status": WARNING, "ms": 158971, "unchecked": True},
        "d5_code_integrity": {"status": OK, "ms": 208},
    }, lang)
    assert word in text, f"[{lang}] unchecked domain must be named in words: {text}"
    # …and only on the domain that was actually unchecked
    assert text.count(word) == 1


def test_telegram_system_screen_silent_when_all_measured(monkeypatch):
    text = _system_screen(monkeypatch, {
        "d1_data_pipeline": {"status": WARNING, "ms": 4},
        "d5_code_integrity": {"status": OK, "ms": 208},
    }, "ru")
    assert "не проверялся" not in text
