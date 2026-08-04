"""ADR-061 — evidence gate + advisory / eligibility gate in the money-path allocator.

Pins the four defects found on 2026-08-02 (D1–D4):

* D1  12 adapters read ``adapter_status.json`` by an obsolete schema and return a
      hardcoded ``DEFAULT_APY_PCT`` that was stamped ``apy_source="live"``.
* D2  ``morpho_steakhouse`` has no adapter class → ranked forever on the registry
      literal 6.5 % while the observed value (3.4657 %) sat unread in
      ``adapter_status.json``; it held 40 % of the book.
* D3  advisory adapters (``IS_ADVISORY``) were excluded on the live path but NOT
      on the registry-merge path → 15 % of the book in advisory pools.
* D4  ``spark_susds.is_gsm_compliant()`` is False (invariant 10, Sky/sUSDS GSM
      gate) yet it held 5 % — nothing consulted the adapter's own gate.

Offline + deterministic: every test injects its own evidence/universe. No network,
no dependence on the live repo's ``data/``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.allocator.allocator import (


    StrategyAllocator,
    _adapter_class_gate,
    _load_evidenced_apy,
)

def _ts(hours_ago: float = 0.0) -> str:
    """Relative timestamp.

    ADR-060 §L0 / feed-staleness (2026-08-04): an observation is evidence only
    inside EVIDENCE_MAX_AGE_H. These tests pin PROVENANCE (literal vs observation,
    which producer wins a tie), not age — a hardcoded date would make them start
    failing purely because the calendar moved. Intent unchanged; only the clock is.
    """
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


# ── fixtures ────────────────────────────────────────────────────────────────


def _write(path: Path, doc: dict) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture()
def orch(tmp_path: Path) -> Path:
    """Orchestrator snapshot: one observed pool, one that failed to poll."""
    return _write(tmp_path / "adapter_orchestrator_status.json", {
        "generated_at": _ts(9),
        "adapters": [
            {"protocol": "pendle", "tier": "T3", "status": "ok",
             "apy_pct": 13.9419, "tvl_usd": 7_006_315.0, "live_data": True,
             "last_updated": _ts(9)},
            {"protocol": "compound_v3", "tier": "T1", "status": "error",
             "apy_pct": None, "tvl_usd": 1_500_000_000.0, "live_data": False},
        ],
    })


@pytest.fixture()
def status(tmp_path: Path) -> Path:
    """adapter_status.json — ``live_apy`` non-null == OBSERVED, null == not."""
    return _write(tmp_path / "adapter_status.json", {
        "generated_at": _ts(1),
        "adapters": {
            # observed
            "maple": {"apy": 5.1097, "live_apy": 5.1097, "fallback_apy": 4.82},
            "morpho_steakhouse": {"apy": 3.4657, "live_apy": 3.4657, "fallback_apy": 6.5},
            "aave_v3": {"apy": 3.2731, "live_apy": 3.2731, "fallback_apy": 3.5},
            # NOT observed — ``apy`` merely echoes the literal
            "frax": {"apy": 7.5, "live_apy": None, "fallback_apy": 7.5},
            "sdai": {"apy": 5.5, "live_apy": None, "fallback_apy": 5.5},
        },
    })


# ── D1/D2: only an OBSERVED reading is evidence ─────────────────────────────


def test_literal_is_never_evidence(orch: Path, status: Path) -> None:
    ev = _load_evidenced_apy(orch, status)
    assert set(ev) == {"pendle", "maple", "morpho_steakhouse", "aave_v3"}
    # D2: morpho ranks on the observed 3.4657 %, never on the 6.5 % literal.
    assert ev["morpho_steakhouse"][0] == pytest.approx(0.034657)
    # A ``live_apy: null`` pool contributes nothing, however high its literal is.
    assert "frax" not in ev and "sdai" not in ev


def test_unpolled_orchestrator_entry_is_not_evidence(orch: Path, status: Path) -> None:
    """``live_data: false`` means the poll FAILED — not a zero-yield observation."""
    assert "compound_v3" not in _load_evidenced_apy(orch, status)


def test_out_of_band_reading_fails_closed(tmp_path: Path, orch: Path) -> None:
    """A 900 % reading is a malformed feed, not an opportunity."""
    st = _write(tmp_path / "s.json", {
        "generated_at": _ts(1),
        "adapters": {"x": {"live_apy": 900.0}, "y": {"live_apy": -3.0},
                     "z": {"live_apy": "5.0"}},
    })
    assert _load_evidenced_apy(orch, st).keys() == {"pendle"}


def test_fresher_producer_wins_on_divergence(tmp_path: Path) -> None:
    """D6: two producers disagree → the fresher one wins, deterministically."""
    orch = _write(tmp_path / "o.json", {
        "generated_at": _ts(9),
        "adapters": [{"protocol": "p", "status": "ok", "apy_pct": 13.94,
                      "live_data": True}],
    })
    newer = _write(tmp_path / "n.json", {
        "generated_at": _ts(1),
        "adapters": {"p": {"live_apy": 8.0}},
    })
    assert _load_evidenced_apy(orch, newer)["p"] == (pytest.approx(0.08),
                                                     "adapter_status_live")
    older = _write(tmp_path / "old.json", {
        "generated_at": _ts(40),
        "adapters": {"p": {"live_apy": 8.0}},
    })
    assert _load_evidenced_apy(orch, older)["p"][1] == "orchestrator_live"


def test_unreadable_evidence_source_never_raises(tmp_path: Path) -> None:
    assert _load_evidenced_apy(tmp_path / "nope.json", tmp_path / "also-nope.json") == {}


# ── D3/D4: advisory and adapter-eligibility gates ───────────────────────────


def test_advisory_adapter_cannot_be_funded() -> None:
    """Invariant 9 — advisory adapters never receive capital, by EITHER path."""
    for advisory in ("susde", "extra_finance_base"):
        allowed, reason = _adapter_class_gate(advisory)
        assert allowed is False and reason == "advisory", advisory


def test_sky_susds_gsm_gate_is_consulted() -> None:
    """Invariant 10 — Sky/sUSDS stays at 0 % until the GSM delay is confirmed."""
    allowed, reason = _adapter_class_gate("spark_susds")
    assert allowed is False and reason == "gsm_not_confirmed"


def test_generic_apy_band_is_not_a_funding_gate() -> None:
    """The per-adapter MIN/MAX_APY band must NOT act as a policy threshold.

    ``compound_v3.is_eligible()`` is False today (its live APY is unavailable),
    but its APY band is a feed-sanity check owned by the adapter, not by
    RiskPolicy. Gating funding on it would install an undeclared APY floor —
    so the gate must consider only the explicit GSM activation invariant.
    """
    assert _adapter_class_gate("compound_v3") == (True, None)


def test_unknown_protocol_is_not_blocked_by_the_class_gate() -> None:
    """No adapter class is not, by itself, a disqualification (D2's morpho)."""
    assert _adapter_class_gate("morpho_steakhouse") == (True, None)


def test_eligibility_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        IS_ADVISORY = False

        def is_gsm_compliant(self):  # noqa: D401 — raises on purpose
            raise RuntimeError("feed down")

    import spa_core.adapters as adapters_pkg
    monkeypatch.setattr(adapters_pkg, "ADAPTER_REGISTRY",
                        [("boom", "T2", _Boom)], raising=True)
    assert _adapter_class_gate("boom") == (False, "gsm_gate_error")


# ── end-to-end through the allocator ────────────────────────────────────────


def _allocator(tmp_path: Path, evidence: dict[str, float]) -> StrategyAllocator:
    """Allocator over a registry of 4 pools; ``evidence`` is injected verbatim."""
    _write(tmp_path / "registry.json", {"adapters": {
        "morpho_steakhouse": {"status": "active", "tier": 1, "fallback_apy": 0.065,
                              "chain": "ethereum"},
        "maple": {"status": "active", "tier": 2, "fallback_apy": 0.0482,
                  "chain": "ethereum"},
        "frax": {"status": "active", "tier": 2, "fallback_apy": 0.075,
                 "chain": "ethereum"},
        "susde": {"status": "active", "tier": 3, "fallback_apy": 0.12,
                  "chain": "ethereum"},
    }})
    _write(tmp_path / "orch.json", {"generated_at": _ts(9),
                                    "adapters": []})
    _write(tmp_path / "scores.json", {})
    return StrategyAllocator(
        status_path=tmp_path / "orch.json",
        risk_scores_path=tmp_path / "scores.json",
        registry_path=tmp_path / "registry.json",
        allocation_model="optimized_yield",
        strategy_loop_enabled=False,
        live_apy_provider=evidence,   # injected map IS the evidence (test contract)
    )


def test_unevidenced_pool_gets_no_capital(tmp_path: Path) -> None:
    """The 7.5 % literal outranks everything — and still receives nothing."""
    res = _allocator(tmp_path, {"morpho_steakhouse": 0.034657, "maple": 0.051097,
                                "aave_v3": 0.032731}).allocate()
    assert res.evidence_gate_applied is True
    assert "frax" not in res.target_usd
    assert res.blocked_protocols.get("frax") == "unevidenced"
    # D3: advisory blocked on the registry path too (this is the path that leaked).
    assert "susde" not in res.target_usd
    assert res.blocked_protocols.get("susde") == "advisory"


def test_evidenced_pool_ranks_on_the_observed_value_not_the_literal(
    tmp_path: Path,
) -> None:
    """D2 pinned: morpho is ranked at 3.4657 %, never at the registry's 6.5 %."""
    res = _allocator(tmp_path, {"morpho_steakhouse": 0.034657,
                                "maple": 0.051097}).allocate()
    assert res.apy_used["morpho_steakhouse"] == pytest.approx(3.4657, abs=1e-3)
    assert res.apy_sources["morpho_steakhouse"] == "live"


def test_gate_disabled_when_evidence_source_is_broken(tmp_path: Path) -> None:
    """Fail-safe: an unreadable evidence source must NOT empty the book.

    Below ``_EVIDENCE_MIN_COVERAGE`` the allocator keeps the legacy universe and
    says so loudly — an all-cash collapse caused by a missing file would itself
    be a money-path incident.
    """
    res = _allocator(tmp_path, {"maple": 0.051097}).allocate()   # 1 < 3
    assert res.evidence_gate_applied is False
    assert any("evidence gate НЕ применён" in n for n in res.notes)
    # …but the class gate is unconditional: advisory never funded, ever.
    assert "susde" not in res.target_usd


def test_blocked_capital_is_always_explained(tmp_path: Path) -> None:
    """No silent omissions: every refusal is named in the cycle notes."""
    res = _allocator(tmp_path, {"morpho_steakhouse": 0.034657, "maple": 0.051097,
                                "aave_v3": 0.032731}).allocate()
    note = next(n for n in res.notes if "evidence gate ON" in n)
    for proto in res.blocked_protocols:
        assert proto in note


def test_timezone_suffix_does_not_flip_the_freshness_tiebreak(tmp_path: Path) -> None:
    """``…Z`` vs ``…+00:00`` must compare as instants, not as strings.

    Lexicographically "Z" > "+", so a string compare would call the OLDER
    ``Z``-stamped producer fresher and silently rank the money path on the stale
    number. Same instants, different spellings → the newer one still wins.
    """
    orch = _write(tmp_path / "o.json", {
        "generated_at": _ts(9),          # older, "Z" spelling
        "adapters": [{"protocol": "p", "status": "ok", "apy_pct": 13.94,
                      "live_data": True}],
    })
    st = _write(tmp_path / "s.json", {
        "generated_at": _ts(1),     # newer, offset spelling
        "adapters": {"p": {"live_apy": 8.0}},
    })
    assert _load_evidenced_apy(orch, st)["p"][1] == "adapter_status_live"


def test_unparseable_timestamp_keeps_the_incumbent(tmp_path: Path) -> None:
    """Fail-CLOSED: an unreadable timestamp must not win a money-path tie-break."""
    orch = _write(tmp_path / "o.json", {
        "generated_at": _ts(9),
        "adapters": [{"protocol": "p", "status": "ok", "apy_pct": 13.94,
                      "live_data": True}],
    })
    st = _write(tmp_path / "s.json", {
        "generated_at": "not-a-timestamp",
        "adapters": {"p": {"live_apy": 8.0}},
    })
    assert _load_evidenced_apy(orch, st)["p"][1] == "orchestrator_live"
