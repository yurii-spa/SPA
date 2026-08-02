"""ADR-063 (D1) — adapters read ``adapter_status.json`` by its ACTUAL schema, and
never substitute a hardcoded constant for a missing observation.

The defect (measured 2026-08-02): the file moved its per-protocol payload under
``adapters``, but twelve adapters still looked at the TOP level, so every read
found nothing. Nine then returned their ``DEFAULT_APY_PCT`` — which the WS1.1
provider stamped ``apy_source="live"``, letting a literal from 2026-06 rank
money-path capital (``spark_susds`` ranked at 5.5 % while its observed 3.3192 %
sat unread in the same file). Three returned ``None`` honestly but were equally
blind: their live values were in the file too.

Offline + deterministic: every test writes its own status file into ``tmp_path``.
"""
from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import pytest

from spa_core.adapters.status_reader import (
    read_live_apy_pct,
    read_status_block,
    read_status_doc,
)

# The twelve adapters this ADR repaired: (protocol, module suffix).
PATCHED = [
    "fluid_fusdc", "sfrax", "spark_susds", "susde", "wusdm", "scrvusd",
    "stusd", "sdai", "frax", "aave_v3_optimism", "aave_v3_polygon", "compound_v3",
]


def _write(dir_: Path, doc: dict) -> Path:
    (dir_ / "adapter_status.json").write_text(json.dumps(doc), encoding="utf-8")
    return dir_


def _adapter(protocol: str, data_dir: Path):
    mod = importlib.import_module(f"spa_core.adapters.{protocol}_adapter")
    cls = next(
        v for v in vars(mod).values()
        if isinstance(v, type) and getattr(v, "PROTOCOL", None) == protocol
    )
    return cls(data_dir=data_dir)


# ── the reader itself ───────────────────────────────────────────────────────


def test_modern_schema_live_apy_is_read(tmp_path: Path) -> None:
    _write(tmp_path, {"adapters": {"sfrax": {"apy": 6.0, "live_apy": 4.21,
                                             "fallback_apy": 6.0}}})
    assert read_live_apy_pct("sfrax", tmp_path) == pytest.approx(4.21)


def test_apy_field_is_never_used_as_evidence(tmp_path: Path) -> None:
    """THE regression: ``apy`` echoes ``fallback_apy`` when nothing was observed.

    Reading it would re-import the very literal this ADR removes, while looking
    like a fix.
    """
    _write(tmp_path, {"adapters": {"frax": {"apy": 7.5, "live_apy": None,
                                            "fallback_apy": 7.5}}})
    assert read_live_apy_pct("frax", tmp_path) is None


def test_absent_protocol_and_unreadable_file_give_none(tmp_path: Path) -> None:
    _write(tmp_path, {"adapters": {"sdai": {"live_apy": 5.0}}})
    assert read_live_apy_pct("nobody", tmp_path) is None
    assert read_live_apy_pct("sdai", tmp_path / "missing-dir") is None
    (tmp_path / "adapter_status.json").write_text("{not json", encoding="utf-8")
    assert read_live_apy_pct("sdai", tmp_path) is None
    assert read_status_doc(tmp_path) == {}


@pytest.mark.parametrize("value", [900.0, float("nan"), float("inf"), "5.0", True, None])
def test_malformed_reading_is_not_a_reading(tmp_path: Path, value) -> None:
    """Non-numeric / non-finite / absurd values are a broken feed, not data."""
    _write(tmp_path, {"adapters": {"stusd": {"live_apy": value}}})
    assert read_live_apy_pct("stusd", tmp_path) is None


@pytest.mark.parametrize("value", [0, 0.0, -1.0, -3.5])
def test_observed_zero_or_negative_survives(tmp_path: Path, value) -> None:
    """An observed 0 % / negative APY is DATA, not a malformed feed.

    Dropping it would collapse "we observed zero" into "we observed nothing" —
    the exact conflation this module exists to end — and would silently discard a
    genuine warning signal. Whether such a pool may be funded is a POLICY call
    made downstream. A first version of the band rejected these and existing
    compound_v3 tests caught it.
    """
    _write(tmp_path, {"adapters": {"compound_v3": {"live_apy": value}}})
    assert read_live_apy_pct("compound_v3", tmp_path) == pytest.approx(float(value))


def test_legacy_top_level_block_still_readable(tmp_path: Path) -> None:
    """Legacy blocks (morpho_steakhouse, aave_arbitrum, pendle_pt) predate the
    ``adapters`` section and carry no ``live_apy``; there ``apy`` IS the reading."""
    _write(tmp_path, {"morpho_steakhouse": {"apy": 3.4657, "tier": "T1"}})
    assert read_live_apy_pct("morpho_steakhouse", tmp_path) == pytest.approx(3.4657)


def test_modern_section_wins_over_legacy_key(tmp_path: Path) -> None:
    _write(tmp_path, {
        "adapters": {"sdai": {"live_apy": 4.0}},
        "sdai": {"apy": 5.5},
    })
    assert read_live_apy_pct("sdai", tmp_path) == pytest.approx(4.0)


def test_status_block_exposes_non_apy_fields(tmp_path: Path) -> None:
    """The schema bug also blanked sibling fields (gsm_hours, peg price)."""
    _write(tmp_path, {"adapters": {"spark_susds": {"live_apy": 3.3, "gsm_hours": 72}}})
    assert read_status_block("spark_susds", tmp_path).get("gsm_hours") == 72


# ── the twelve adapters ─────────────────────────────────────────────────────


@pytest.mark.parametrize("protocol", PATCHED)
def test_adapter_returns_observed_value(protocol: str, tmp_path: Path) -> None:
    _write(tmp_path, {"adapters": {protocol: {"apy": 99.0, "live_apy": 4.25,
                                              "fallback_apy": 99.0}}})
    assert _adapter(protocol, tmp_path).get_apy() == pytest.approx(4.25)


@pytest.mark.parametrize("protocol", PATCHED)
def test_adapter_returns_none_instead_of_its_literal(protocol: str, tmp_path: Path) -> None:
    """No fake fallback (.claude/rules/adapters.md): no observation ⇒ ``None``.

    Pins the exact defect — the adapter must NOT answer with DEFAULT_APY_PCT.
    """
    _write(tmp_path, {"adapters": {protocol: {"apy": 7.5, "live_apy": None}}})
    adapter = _adapter(protocol, tmp_path)
    apy = adapter.get_apy()
    assert apy is None, f"{protocol} substituted {apy} for a missing observation"
    assert adapter.get_yield_info().apy is None


@pytest.mark.parametrize("protocol", PATCHED)
def test_no_public_method_raises_without_an_observation(protocol: str, tmp_path: Path) -> None:
    """``None`` must flow through every surface, not crash one of them.

    Found 23 such crashes when the change was first made — including three that
    predated it (compound_v3 already returned ``None``).
    """
    _write(tmp_path, {"adapters": {protocol: {"live_apy": None}}})
    adapter = _adapter(protocol, tmp_path)
    for name, method in inspect.getmembers(adapter, predicate=inspect.ismethod):
        if name.startswith("_"):
            continue
        sig = inspect.signature(method)
        if any(p.default is inspect.Parameter.empty
               and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
               for p in sig.parameters.values()):
            continue
        method()   # must not raise


@pytest.mark.parametrize("protocol", PATCHED)
def test_eligibility_fails_closed_without_an_observation(protocol: str, tmp_path: Path) -> None:
    _write(tmp_path, {"adapters": {protocol: {"live_apy": None}}})
    adapter = _adapter(protocol, tmp_path)
    if hasattr(adapter, "is_eligible"):
        assert adapter.is_eligible() is False


def test_simulation_helper_keeps_its_deliberate_literal(tmp_path: Path) -> None:
    """``compound_v3._apy_for_simulation`` is EXEMPT — and that is on purpose.

    Its literal keeps the advisory paper simulation deterministic; it never ranks
    capital and never feeds the track. The no-fake-fallback rule targets
    ``get_apy()``. An automated sweep did change it while making this ADR, and
    that broke five methods — this test pins the boundary.
    """
    _write(tmp_path, {"adapters": {"compound_v3": {"live_apy": None}}})
    adapter = _adapter("compound_v3", tmp_path)
    assert adapter.get_apy() is None
    assert adapter._apy_for_simulation() == pytest.approx(adapter.DEFAULT_APY_PCT)
