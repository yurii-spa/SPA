"""Feed staleness: a network hiccup must not move capital (2026-08-04).

At 15:14Z one failed HTTP request to DeFiLlama blanked ``live_apy`` for all 34
adapters. The evidence gate then correctly concluded "nothing is observable" —
which, had a cycle been running, would have evacuated the whole book to cash on
the strength of a single timeout.

The rule was binary: observed now, or not observed. It made no distinction
between "this protocol stopped being observable" and "the feed blinked" — two
different events with different correct responses. These tests pin the fix in
both halves: the producer carries the last-known-good reading forward with its
OWN timestamp, and the consumer accepts it only while it is young enough.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.allocator.allocator import _EVIDENCE_MAX_AGE_H, _load_evidenced_apy


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _write(tmp_path: Path, adapters: dict, generated_hours_ago: float = 0.0) -> tuple:
    orch = tmp_path / "orch.json"
    orch.write_text(json.dumps({"generated_at": _iso(generated_hours_ago),
                                "adapters": []}), encoding="utf-8")
    st = tmp_path / "adapter_status.json"
    st.write_text(json.dumps({"generated_at": _iso(generated_hours_ago),
                              "adapters": adapters}), encoding="utf-8")
    return orch, st


# ── consumer: the age window ────────────────────────────────────────────────


def test_carried_forward_reading_survives_a_failed_fetch(tmp_path: Path) -> None:
    """THE case: the feed blinked, yesterday's observation is still evidence."""
    orch, st = _write(tmp_path, {
        "maple": {"live_apy": 5.06, "live_apy_as_of": _iso(6), "live_apy_fresh": False}})
    ev = _load_evidenced_apy(orch, st)
    assert ev["maple"][0] == pytest.approx(0.0506)


def test_observation_older_than_the_window_stops_being_evidence(tmp_path: Path) -> None:
    """Staleness DOES invalidate — the window is a limit, not an amnesty."""
    orch, st = _write(tmp_path, {
        "maple": {"live_apy": 5.06, "live_apy_as_of": _iso(_EVIDENCE_MAX_AGE_H + 1)}})
    assert "maple" not in _load_evidenced_apy(orch, st)


def test_age_is_measured_from_observation_not_from_file_write(tmp_path: Path) -> None:
    """A carried-forward value must age on its OWN clock.

    The producer rewrites the file every run, so trusting the file timestamp would
    keep a month-old reading permanently 'fresh'.
    """
    orch, st = _write(tmp_path, {
        "maple": {"live_apy": 5.06, "live_apy_as_of": _iso(_EVIDENCE_MAX_AGE_H + 5)},
    }, generated_hours_ago=0.0)          # file written seconds ago
    assert "maple" not in _load_evidenced_apy(orch, st)


def test_unparseable_or_missing_as_of_is_not_evidence(tmp_path: Path) -> None:
    """Unknown age is not evidence — fail-CLOSED."""
    orch, st = _write(tmp_path, {"a": {"live_apy": 5.0, "live_apy_as_of": "не дата"}})
    assert "a" not in _load_evidenced_apy(orch, st)


def test_null_live_apy_is_still_not_evidence(tmp_path: Path) -> None:
    """The window does not resurrect a value that was never observed."""
    orch, st = _write(tmp_path, {"a": {"live_apy": None, "live_apy_as_of": _iso(1)}})
    assert "a" not in _load_evidenced_apy(orch, st)


# ── producer: last-known-good is preserved ──────────────────────────────────


def test_producer_carries_last_good_forward_when_the_fetch_fails(tmp_path: Path,
                                                                 monkeypatch) -> None:
    """A failed fetch must not blank live_apy for every adapter."""
    from spa_core.monitoring import adapter_status_generator as gen

    out = tmp_path / "adapter_status.json"
    out.write_text(json.dumps({"generated_at": _iso(6), "adapters": {
        "maple": {"live_apy": 5.06, "live_apy_as_of": _iso(6), "fallback_apy": 4.82}}}),
        encoding="utf-8")
    reg = tmp_path / "adapter_registry.json"
    reg.write_text(json.dumps({"adapters": {
        "maple": {"protocol": "Maple", "fallback_apy": 0.0482, "tier": 2,
                  "chain": "ethereum", "status": "active"}}}), encoding="utf-8")

    monkeypatch.setattr(gen, "_fetch_defillama", lambda **kw: None)   # feed down
    doc = gen.generate(registry_path=reg, output_path=out)

    entry = doc["adapters"]["maple"]
    assert entry["live_apy"] == pytest.approx(5.06)     # preserved, not blanked
    assert entry["live_apy_fresh"] is False             # honestly labelled
    assert doc["feed_reachable"] is False               # the incident is visible
    assert doc["live_fresh_count"] == 0


def test_feed_reachable_is_separate_from_protocol_observability(tmp_path: Path,
                                                                monkeypatch) -> None:
    """"The feed did not answer" is an infrastructure incident to alert on — never
    evidence that protocols stopped being observable. The two must stay separate
    fields, or a consumer cannot tell an outage from a market fact."""
    from spa_core.monitoring import adapter_status_generator as gen
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"adapters": {"maple": {
        "protocol": "Maple", "fallback_apy": 0.0482, "tier": 2,
        "chain": "ethereum", "status": "active"}}}), encoding="utf-8")
    monkeypatch.setattr(gen, "_fetch_defillama", lambda **kw: None)
    doc = gen.generate(registry_path=reg, output_path=tmp_path / "absent.json")
    assert doc["feed_reachable"] is False
    assert doc["adapters"]["maple"]["live_apy"] is None      # nothing to carry
    assert doc["adapters"]["maple"]["live_apy_fresh"] is False
