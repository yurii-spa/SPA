"""
test_competitive_watch.py — WS-E Proof-of-Risk competitive early-warning monitor.

Verifies the Section-7 watch-threshold engine:
  * each Section-7 trigger is a coded check
  * unknown / unsourced input → WATCH (fail-CLOSED, never silent SAFE)
  * a sourced breach → BREACHED + traceable evidence
  * manual-pending is honest (never a fabricated competitor state)
  * deterministic re-run is byte-identical
  * adversarial: a spoofed / ambiguous competitor signal degrades to WATCH
  * monotonic-honest: a sourced BREACHED cannot silently revert to SAFE
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.monitoring import competitive_watch as cw

FIXED_TS = "2026-06-28T00:00:00+00:00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_inputs(data_dir: Path, observations: dict) -> None:
    (data_dir / cw._SIGNAL_INPUT_FILENAME).write_text(
        json.dumps({"observations": observations}), encoding="utf-8"
    )


def _run(data_dir: Path, ts: str = FIXED_TS) -> dict:
    return cw.CompetitiveWatchMonitor(data_dir=data_dir, generated_at=ts).run(send=False)


# ---------------------------------------------------------------------------
# E1 — each Section-7 trigger is a coded check
# ---------------------------------------------------------------------------
def test_all_section7_triggers_are_coded_checks():
    ids = {t.signal_id for t in cw.SECTION7_THRESHOLDS}
    assert ids == {
        "exponential_yo_refusal_log",
        "exponential_yo_exit_nav",
        "chaos_gauntlet_investor_exit_nav",
        "kraken_coinbase_risk_rationale",
    }


def test_each_threshold_has_category_and_competitors():
    for t in cw.SECTION7_THRESHOLDS:
        assert t.category
        assert t.competitors  # non-empty
        assert t.breach_meaning


def test_report_emits_one_signal_per_threshold(tmp_path):
    rep = _run(tmp_path)
    assert rep["n_signals"] == len(cw.SECTION7_THRESHOLDS)
    emitted = {s["signal_id"] for s in rep["signals"]}
    assert emitted == {t.signal_id for t in cw.SECTION7_THRESHOLDS}


# ---------------------------------------------------------------------------
# Fail-CLOSED: unknown / no input → WATCH (never silent SAFE)
# ---------------------------------------------------------------------------
def test_no_input_all_watch_manual_pending(tmp_path):
    rep = _run(tmp_path)
    assert rep["overall_state"] == cw.WATCH
    for s in rep["signals"]:
        assert s["state"] == cw.WATCH
        assert s["manual_pending"] is True
    # No signal is ever silently SAFE without a source.
    assert rep["counts"][cw.SAFE] == 0
    assert sorted(rep["manual_pending_ids"]) == sorted(
        t.signal_id for t in cw.SECTION7_THRESHOLDS
    )


def test_missing_input_file_is_fail_closed_not_safe(tmp_path):
    # No competitive_signals_input.json on disk at all.
    obs = cw.load_signal_inputs(tmp_path)
    assert obs == {}
    rep = _run(tmp_path)
    assert all(s["state"] == cw.WATCH for s in rep["signals"])


def test_corrupt_input_file_fail_closed(tmp_path):
    (tmp_path / cw._SIGNAL_INPUT_FILENAME).write_text("{not json", encoding="utf-8")
    rep = _run(tmp_path)
    assert all(s["state"] == cw.WATCH for s in rep["signals"])
    assert rep["counts"][cw.SAFE] == 0


# ---------------------------------------------------------------------------
# Sourced verdicts → SAFE / BREACHED with traceable evidence
# ---------------------------------------------------------------------------
def test_sourced_breach_is_breached_with_evidence(tmp_path):
    _write_inputs(tmp_path, {
        "exponential_yo_refusal_log": {
            "verdict": "breached",
            "as_of": "2026-06-20",
            "evidence": "Exponential.fi blog announced public refusal log",
            "source_url": "https://example.com/post",
        },
    })
    rep = _run(tmp_path)
    sig = next(s for s in rep["signals"]
               if s["signal_id"] == "exponential_yo_refusal_log")
    assert sig["state"] == cw.BREACHED
    assert sig["manual_pending"] is False
    assert sig["as_of"] == "2026-06-20"
    assert "refusal log" in sig["evidence"]
    assert sig["source_url"] == "https://example.com/post"
    assert rep["overall_state"] == cw.BREACHED
    assert "exponential_yo_refusal_log" in rep["breached_ids"]


def test_sourced_safe_is_safe(tmp_path):
    _write_inputs(tmp_path, {
        "kraken_coinbase_risk_rationale": {
            "verdict": "safe",
            "as_of": "2026-06-25",
            "evidence": "manual review: no retail risk-rationale feature found",
        },
    })
    rep = _run(tmp_path)
    sig = next(s for s in rep["signals"]
               if s["signal_id"] == "kraken_coinbase_risk_rationale")
    assert sig["state"] == cw.SAFE
    assert sig["manual_pending"] is False
    # The others stay WATCH (fail-closed).
    others = [s for s in rep["signals"] if s["signal_id"] != "kraken_coinbase_risk_rationale"]
    assert all(s["state"] == cw.WATCH for s in others)


# ---------------------------------------------------------------------------
# manual_pending never fabricated
# ---------------------------------------------------------------------------
def test_explicit_manual_pending_stays_watch(tmp_path):
    _write_inputs(tmp_path, {
        "exponential_yo_exit_nav": {"manual_pending": True},
    })
    rep = _run(tmp_path)
    sig = next(s for s in rep["signals"]
               if s["signal_id"] == "exponential_yo_exit_nav")
    assert sig["state"] == cw.WATCH
    assert sig["manual_pending"] is True


# ---------------------------------------------------------------------------
# ADVERSARIAL — spoofed / ambiguous input degrades to WATCH, not SAFE
# ---------------------------------------------------------------------------
def test_spoofed_safe_without_source_degrades_to_watch(tmp_path):
    # Attacker tries to assert SAFE/clear with NO date and NO evidence.
    _write_inputs(tmp_path, {
        "exponential_yo_refusal_log": {"verdict": "safe"},
    })
    rep = _run(tmp_path)
    sig = next(s for s in rep["signals"]
               if s["signal_id"] == "exponential_yo_refusal_log")
    assert sig["state"] == cw.WATCH          # NOT SAFE
    assert sig["manual_pending"] is True


def test_unrecognised_verdict_degrades_to_watch(tmp_path):
    _write_inputs(tmp_path, {
        "exponential_yo_exit_nav": {
            "verdict": "probably_fine_trust_me",
            "as_of": "2026-06-20",
            "evidence": "vibes",
        },
    })
    rep = _run(tmp_path)
    sig = next(s for s in rep["signals"]
               if s["signal_id"] == "exponential_yo_exit_nav")
    assert sig["state"] == cw.WATCH


def test_bad_date_breach_claim_degrades_to_watch(tmp_path):
    _write_inputs(tmp_path, {
        "chaos_gauntlet_investor_exit_nav": {
            "verdict": "breached",
            "as_of": "not-a-date",
            "evidence": "something",
        },
    })
    rep = _run(tmp_path)
    sig = next(s for s in rep["signals"]
               if s["signal_id"] == "chaos_gauntlet_investor_exit_nav")
    assert sig["state"] == cw.WATCH


def test_unknown_signal_id_in_input_is_ignored(tmp_path):
    _write_inputs(tmp_path, {
        "totally_made_up_signal": {
            "verdict": "safe", "as_of": "2026-06-20", "evidence": "x",
        },
    })
    rep = _run(tmp_path)
    # No new signal introduced; all known signals fail-closed to WATCH.
    assert rep["n_signals"] == len(cw.SECTION7_THRESHOLDS)
    assert all(s["state"] == cw.WATCH for s in rep["signals"])


def test_non_dict_observation_degrades_to_watch():
    state, _ = cw.normalize_observation("breached")  # malformed
    assert state == cw.WATCH
    state, _ = cw.normalize_observation(None)
    assert state == cw.WATCH


# ---------------------------------------------------------------------------
# MONOTONIC-HONEST — sourced BREACHED cannot silently revert to SAFE/WATCH
# ---------------------------------------------------------------------------
def test_sourced_breach_held_when_input_disappears(tmp_path):
    # Run 1: sourced breach.
    _write_inputs(tmp_path, {
        "exponential_yo_exit_nav": {
            "verdict": "breached",
            "as_of": "2026-06-20",
            "evidence": "YO shipped exit-NAV-by-size",
        },
    })
    rep1 = _run(tmp_path)
    assert next(s for s in rep1["signals"]
                if s["signal_id"] == "exponential_yo_exit_nav")["state"] == cw.BREACHED

    # Run 2: the input vanishes (would naively → WATCH). Must HOLD breach.
    (tmp_path / cw._SIGNAL_INPUT_FILENAME).unlink()
    rep2 = _run(tmp_path)
    held = next(s for s in rep2["signals"]
                if s["signal_id"] == "exponential_yo_exit_nav")
    assert held["state"] == cw.BREACHED
    assert held["manual_pending"] is False
    assert held["evidence"]  # carried forward


def test_sourced_breach_can_be_retracted_only_with_sourced_safe(tmp_path):
    _write_inputs(tmp_path, {
        "exponential_yo_exit_nav": {
            "verdict": "breached", "as_of": "2026-06-20",
            "evidence": "YO shipped exit-NAV",
        },
    })
    _run(tmp_path)
    # A SOURCED retraction (explicit safe with date+evidence) is honored.
    _write_inputs(tmp_path, {
        "exponential_yo_exit_nav": {
            "verdict": "safe", "as_of": "2026-06-27",
            "evidence": "YO removed the feature (retraction confirmed)",
        },
    })
    rep = _run(tmp_path)
    sig = next(s for s in rep["signals"]
               if s["signal_id"] == "exponential_yo_exit_nav")
    assert sig["state"] == cw.SAFE
    assert sig["as_of"] == "2026-06-27"


# ---------------------------------------------------------------------------
# Alerting — fire only on NEW breach
# ---------------------------------------------------------------------------
def test_newly_breached_detects_new_transition():
    prev = {"signals": [{"signal_id": "a", "state": cw.WATCH}]}
    cur = {"signals": [{"signal_id": "a", "state": cw.BREACHED}]}
    assert cw.newly_breached(cur, prev) == ["a"]
    # Already breached → not "new"
    assert cw.newly_breached(cur, cur) == []


# ---------------------------------------------------------------------------
# DETERMINISM — re-run is byte-identical
# ---------------------------------------------------------------------------
def test_deterministic_rerun_byte_identical(tmp_path):
    _write_inputs(tmp_path, {
        "exponential_yo_refusal_log": {
            "verdict": "breached", "as_of": "2026-06-20", "evidence": "blog",
        },
    })
    rep_a = cw.CompetitiveWatchMonitor(data_dir=tmp_path, generated_at=FIXED_TS).collect()
    rep_b = cw.CompetitiveWatchMonitor(data_dir=tmp_path, generated_at=FIXED_TS).collect()
    assert json.dumps(rep_a, sort_keys=True) == json.dumps(rep_b, sort_keys=True)


def test_written_file_is_valid_and_labeled_internal(tmp_path):
    rep = _run(tmp_path)
    out = tmp_path / cw._OUTPUT_FILENAME
    assert out.exists()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == "spa.competitive_watch.v1"
    assert doc["public_naming_owner_gated"] is True
    assert doc["is_internal_surface"] is True
    assert "fail_closed_note" in doc


def test_run_never_raises_and_returns_watch_on_error(tmp_path, monkeypatch):
    # Force the write to blow up; run() must still return a fail-closed report.
    def _boom(self, report):
        raise RuntimeError("disk full")
    monkeypatch.setattr(cw.CompetitiveWatchMonitor, "_write", _boom)
    rep = cw.CompetitiveWatchMonitor(data_dir=tmp_path, generated_at=FIXED_TS).run(send=False)
    assert rep["overall_state"] == cw.WATCH  # fail-closed, never SAFE
    assert "error" in rep


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
