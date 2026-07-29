"""
spa_core/tests/test_tier1_status_honesty.py — the Tier-1 rollup must never report
"OK" about a check it did not actually perform.

WHY THIS FILE EXISTS (cycle #35, same class as RISKWIRE #29 and d2_connectivity #31):
`status.build()` derives its whole verdict from exactly TWO detectors —

    live-vs-backtest DIVERGENT   (data/tier1_gate.json → live_vs_backtest.status)
    data integrity   ISSUES      (data/tier1_data_integrity.json → status)

— and both were compared with `==` against the bad value only. Every other outcome,
including "the file is not there", "the file is corrupt", "the audit blew up
(NO_DATA)" and "the divergence check could not decide (insufficient_data)", fell
through to `problems == []` ⇒ `health: "OK"`. The rollup is published on
`/api/tier1/status` and alerts to Telegram ONLY when it sees problems, so a
half-failed pipeline (`run_backtest_tier1.sh` runs under `set +e` — every step's
failure is ignored and the run continues) produced a confident green light and
stayed silent. That is fail-OPEN against invariant #2 (refusal-first).

Contract asserted here:
  • an input that cannot be READ (absent / corrupt / not an object) ⇒ NOT OK;
  • an input that is readable but carries no verdict field ⇒ NOT OK;
  • a detector that reports a non-verdict of its own (`NO_DATA`,
    `insufficient_data`, or any unrecognised value) ⇒ NOT OK — and the unknown
    value is quoted VERBATIM, never swallowed;
  • `unchecked` names what was not measured, and every unchecked reason is also
    visible in `problems` (so the Telegram alert says it, and the pre-existing
    biconditional `health == "ATTENTION" ⟺ problems` in test_tier1_backtest.py
    keeps holding);
  • both detectors clear ⇒ "OK" with `unchecked == []` (the fix must not make
    the rollup permanently red);
  • measured problems are still reported, and reported values still pass through.

Hermetic: `_DATA`/`_OUT` are redirected to `tmp_path`, `write=False`, `alert=False`
— the live data/ dir, the live track and Telegram are never touched.
Pure stdlib + pytest. Deterministic. LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

import pytest

from spa_core.backtesting.tier1 import status as status_mod


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Point the module at an empty tmp data/ dir (nothing is read from the real one)."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(status_mod, "_DATA", d)
    monkeypatch.setattr(status_mod, "_OUT", d / "tier1_status.json")
    return d


def _write(d, name: str, payload) -> None:
    (d / name).write_text(json.dumps(payload))


def _healthy_inputs(d) -> None:
    """The minimum set that makes BOTH detectors actually fire a clean verdict."""
    _write(d, "tier1_gate.json", {
        "eligible_count": 9, "blocked_count": 54,
        "live_vs_backtest": {"status": "ok", "live_apy_pct": 3.7, "expected_apy_pct": 3.748},
    })
    _write(d, "tier1_data_integrity.json", {"status": "CLEAN", "total_issues": 0})
    _write(d, "tier1_verdict.json", {"regime": "NORMAL"})
    _write(d, "tier1_packages.json", {"packages": {
        "conservative": {"status": "available", "blended_net_apy_pct": 3.3, "n_offered": 2},
    }})
    _write(d, "tier1_correlation.json", {"packages": {"conservative": {"diversified_subset_size": 2}}})


def _build(d):
    return status_mod.build(write=False, alert=False)


# ---------------------------------------------------------------------------
# 1. Nothing measured at all must NOT read as OK.
#    This is the exact clean-checkout shape that made test_tier1_e2e red:
#    every field None, packages {}, problems [] — and health "OK".
# ---------------------------------------------------------------------------
def test_empty_data_dir_is_not_ok(data_dir):
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert s["unchecked"], "no Tier-1 input was readable, yet nothing is reported as unchecked"
    assert s["problems"], "health=ATTENTION requires a non-empty problems list"
    # the two detectors are named explicitly — an operator must see WHAT was not checked
    joined = " ".join(s["unchecked"]).lower()
    assert "live-vs-backtest" in joined
    assert "integrity" in joined


def test_unchecked_reasons_are_also_in_problems(data_dir):
    """The Telegram alert is built from `problems` only — unchecked must reach it."""
    s = _build(data_dir)
    for reason in s["unchecked"]:
        assert reason in s["problems"]


def test_health_attention_iff_problems_on_empty_dir(data_dir):
    """The pre-existing biconditional (test_tier1_backtest::test_status_rollup) still holds."""
    s = _build(data_dir)
    assert (s["health"] == "ATTENTION") == bool(s["problems"])


# ---------------------------------------------------------------------------
# 2. Per-input unreadability. Each detector's input is knocked out on its own so
#    a fix that only special-cases "the whole dir is empty" cannot pass.
# ---------------------------------------------------------------------------
def test_missing_gate_file_alone_is_not_ok(data_dir):
    _healthy_inputs(data_dir)
    (data_dir / "tier1_gate.json").unlink()
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert any("live-vs-backtest" in u.lower() for u in s["unchecked"])
    # integrity DID run and was clean → it must not be reported as unchecked
    assert not any("integrity" in u.lower() for u in s["unchecked"])


def test_missing_integrity_file_alone_is_not_ok(data_dir):
    _healthy_inputs(data_dir)
    (data_dir / "tier1_data_integrity.json").unlink()
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert any("integrity" in u.lower() for u in s["unchecked"])
    assert not any("live-vs-backtest" in u.lower() for u in s["unchecked"])


@pytest.mark.parametrize("name", ["tier1_gate.json", "tier1_data_integrity.json"])
def test_corrupt_json_input_is_not_ok(data_dir, name):
    """A truncated write / half-flushed file must not be silently read as 'fine'."""
    _healthy_inputs(data_dir)
    (data_dir / name).write_text('{"status": "CLE')  # truncated
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert s["unchecked"]


@pytest.mark.parametrize("payload", ["[]", '"CLEAN"', "null", "42"])
def test_non_object_input_is_not_ok(data_dir, payload):
    """Valid JSON of the wrong SHAPE (list/str/null/number) is not a verdict either."""
    _healthy_inputs(data_dir)
    (data_dir / "tier1_data_integrity.json").write_text(payload)
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert any("integrity" in u.lower() for u in s["unchecked"])


# ---------------------------------------------------------------------------
# 3. Readable input, but the verdict field is absent → the detector never ran.
# ---------------------------------------------------------------------------
def test_gate_without_live_vs_backtest_block_is_not_ok(data_dir):
    _healthy_inputs(data_dir)
    _write(data_dir, "tier1_gate.json", {"eligible_count": 9, "blocked_count": 54})
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert any("live-vs-backtest" in u.lower() for u in s["unchecked"])


def test_integrity_without_status_field_is_not_ok(data_dir):
    _healthy_inputs(data_dir)
    _write(data_dir, "tier1_data_integrity.json", {"total_issues": 0})
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert any("integrity" in u.lower() for u in s["unchecked"])


# ---------------------------------------------------------------------------
# 4. The detector answered — but its answer is a NON-verdict.
#    data_integrity.audit() returns {"status": "NO_DATA", "error": ...} when the
#    audit itself raises (spa_core/backtesting/tier1/data_integrity.py:32), and
#    gate._live_divergence() returns "insufficient_data" when there is no live
#    APY or no validated net APY. Both used to read as OK.
# ---------------------------------------------------------------------------
def test_integrity_no_data_is_not_ok(data_dir):
    _healthy_inputs(data_dir)
    _write(data_dir, "tier1_data_integrity.json",
           {"status": "NO_DATA", "error": "boom", "checked": 0})
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert any("integrity" in u.lower() for u in s["unchecked"])
    # the reported value is passed through verbatim, not normalised away
    assert s["data_integrity"] == "NO_DATA"


def test_divergence_insufficient_data_is_not_ok(data_dir):
    _healthy_inputs(data_dir)
    _write(data_dir, "tier1_gate.json", {
        "eligible_count": 0, "blocked_count": 63,
        "live_vs_backtest": {"status": "insufficient_data",
                             "live_apy_pct": None, "expected_apy_pct": None},
    })
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert any("live-vs-backtest" in u.lower() for u in s["unchecked"])
    assert s["live_vs_backtest"] == "insufficient_data"


@pytest.mark.parametrize("value", ["UNKNOWN", "PENDING", "", "ok "])
def test_unrecognised_integrity_status_is_not_ok(data_dir, value):
    """An unknown vocabulary word is 'not measured', never 'measured and fine'."""
    _healthy_inputs(data_dir)
    _write(data_dir, "tier1_data_integrity.json", {"status": value})
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert any("integrity" in u.lower() for u in s["unchecked"])


def test_unrecognised_value_is_quoted_verbatim_in_the_reason(data_dir):
    """Refusal must say WHAT it saw — a swallowed value cannot be diagnosed."""
    _healthy_inputs(data_dir)
    _write(data_dir, "tier1_data_integrity.json", {"status": "WEIRD_SENTINEL"})
    s = _build(data_dir)
    assert any("WEIRD_SENTINEL" in u for u in s["unchecked"]), s["unchecked"]


# ---------------------------------------------------------------------------
# 5. The fix must NOT make the rollup permanently red: both detectors clearing
#    is still a clean OK, and real problems are still reported as problems.
# ---------------------------------------------------------------------------
def test_both_detectors_clear_is_ok(data_dir):
    _healthy_inputs(data_dir)
    s = _build(data_dir)
    assert s["health"] == "OK"
    assert s["problems"] == []
    assert s["unchecked"] == []


def test_measured_divergence_is_still_a_problem(data_dir):
    _healthy_inputs(data_dir)
    _write(data_dir, "tier1_gate.json", {
        "eligible_count": 9, "blocked_count": 54,
        "live_vs_backtest": {"status": "DIVERGENT", "live_apy_pct": 0.0,
                             "expected_apy_pct": 3.748},
    })
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert "live-vs-backtest DIVERGENT" in s["problems"]
    # a FIRED detector is not an unchecked one
    assert s["unchecked"] == []


def test_measured_integrity_issues_is_still_a_problem(data_dir):
    _healthy_inputs(data_dir)
    _write(data_dir, "tier1_data_integrity.json", {"status": "ISSUES", "total_issues": 3})
    s = _build(data_dir)
    assert s["health"] == "ATTENTION"
    assert any("data integrity: 3 issue(s)" == p for p in s["problems"])
    assert s["unchecked"] == []


def test_reported_values_still_pass_through(data_dir):
    """The rollup keeps reporting the numbers it always reported (no shape regression)."""
    _healthy_inputs(data_dir)
    s = _build(data_dir)
    assert s["model"] == "tier1_status"
    assert s["llm_forbidden"] is True
    assert s["regime"] == "NORMAL"
    assert s["eligible_count"] == 9
    assert s["blocked_count"] == 54
    assert s["data_integrity"] == "CLEAN"
    assert s["live_vs_backtest"] == "ok"
    assert s["diversification_conservative"] == 2
    assert s["packages"]["conservative"] == {
        "status": "available", "net_apy_pct": 3.3,
        "risk_adjusted_apy_pct": None, "worst_case_pct": None, "n": 2,
    }
    assert s["generated_at"].endswith("+00:00")


# ---------------------------------------------------------------------------
# 6. Hermeticity / side-effect guards.
# ---------------------------------------------------------------------------
def test_write_false_writes_nothing(data_dir):
    _healthy_inputs(data_dir)
    before = {p.name for p in data_dir.iterdir()}
    _build(data_dir)
    assert {p.name for p in data_dir.iterdir()} == before
    assert not (data_dir / "tier1_status.json").exists()


def test_write_true_publishes_atomically_into_the_patched_dir(data_dir):
    """write=True must land in the injected dir only, with no .tmp leftovers."""
    _healthy_inputs(data_dir)
    status_mod.build(write=True, alert=False)
    out = data_dir / "tier1_status.json"
    assert out.exists()
    assert json.loads(out.read_text())["health"] == "OK"
    assert not list(data_dir.glob("*.tmp")), "atomic write left a .tmp orphan"


def test_alert_is_not_sent_when_alert_false(data_dir, monkeypatch):
    """alert=False must not reach Telegram even though problems exist."""
    sent = []
    import spa_core.alerts.telegram_client as tc
    monkeypatch.setattr(tc, "send_message", lambda *a, **k: sent.append(a), raising=False)
    s = _build(data_dir)          # empty dir → problems exist
    assert s["problems"]
    assert sent == []
