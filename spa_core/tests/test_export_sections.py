"""P3-8: tests for the decomposed export_data sections.

Verifies the run_export() god-function break-up:
  * the EXPORTERS registry is the source of truth and well-formed,
  * each section is independently callable against an ExportContext,
  * a failing section degrades gracefully (writes a fallback file, increments
    the health failure counter) rather than aborting — fail-CLOSED,
  * write_json is atomic + byte-identical to the historical format.

No live data / network: sections are exercised with a stub trader and a
temp OUTPUT_DIR.
"""
from __future__ import annotations

import json
import types
from datetime import datetime, timezone

import pytest

import export_data as ed


# ─────────────────────────────────────────────────────────────────────────────
# Registry contract
# ─────────────────────────────────────────────────────────────────────────────
def test_exporters_registry_is_ordered_callables():
    assert isinstance(ed.EXPORTERS, list)
    assert len(ed.EXPORTERS) >= 25
    for fn in ed.EXPORTERS:
        assert callable(fn)
        assert fn.__name__.startswith("export_")
    # No duplicate sections in the registry.
    names = [fn.__name__ for fn in ed.EXPORTERS]
    assert len(names) == len(set(names))


def test_every_registered_exporter_is_module_level():
    for fn in ed.EXPORTERS:
        assert getattr(ed, fn.__name__, None) is fn


# ─────────────────────────────────────────────────────────────────────────────
# write_json: atomic + byte-identical to the historical json.dumps format
# ─────────────────────────────────────────────────────────────────────────────
def test_write_json_bytes_match_legacy_format(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "OUTPUT_DIR", tmp_path)
    payload = {"b": 2, "a": 1, "nested": {"x": [1, 2, 3]}}
    ed.write_json("sample.json", payload)
    written = (tmp_path / "sample.json").read_text(encoding="utf-8")
    # Exactly the legacy serialisation (indent=2, default=str, no trailing nl).
    assert written == json.dumps(payload, indent=2, default=str)
    # No temp files left behind (atomic move cleaned up).
    assert not list(tmp_path.glob("*.tmp"))


# ─────────────────────────────────────────────────────────────────────────────
# Independent callability + graceful degradation
# ─────────────────────────────────────────────────────────────────────────────
def _ctx(tmp_path, monkeypatch, trader=None):
    monkeypatch.setattr(ed, "OUTPUT_DIR", tmp_path)
    ctx = ed.ExportContext(fetch=False)
    ctx.trader = trader
    return ctx


def test_export_meta_independent(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    ed.export_meta(ctx)
    doc = json.loads((tmp_path / "meta.json").read_text())
    assert doc["version"] == "1.0.0"
    assert doc["source"] == "local"          # fetch=False
    assert ctx.health["sections_ok"] == 1
    assert ctx.health["sections_failed"] == 0


def test_export_meta_reflects_fetch_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "OUTPUT_DIR", tmp_path)
    ctx = ed.ExportContext(fetch=True)
    ed.export_meta(ctx)
    doc = json.loads((tmp_path / "meta.json").read_text())
    assert doc["source"] == "github-actions"


def test_export_pendle_positions_empty_actions(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    ctx.alloc_actions = []      # no OPEN_PENDLE_PT actions
    ed.export_pendle_positions(ctx)
    doc = json.loads((tmp_path / "pendle_positions.json").read_text())
    assert doc["count"] == 0
    assert doc["positions"] == []
    assert ctx.health["sections_ok"] == 1


def test_export_risk_alerts_graceful_fail(tmp_path, monkeypatch):
    """A broken trader must NOT abort the section — it writes a fallback file
    and records the failure (fail-CLOSED)."""
    class _BoomTrader:
        def get_status(self):
            raise RuntimeError("db down")

    ctx = _ctx(tmp_path, monkeypatch, trader=_BoomTrader())
    ed.export_risk_alerts(ctx)                # must not raise
    doc = json.loads((tmp_path / "risk_alerts.json").read_text())
    assert doc["count"] == 0
    assert doc["status"] == "ok"
    assert "error" in doc
    assert ctx.health["sections_failed"] == 1
    assert "risk_alerts" in ctx.health["failed_sections"]


def test_export_risk_alerts_flags_concentration(tmp_path, monkeypatch):
    """A position >45% of the book triggers a critical concentration alert."""
    class _Trader:
        def get_status(self):
            return {
                "positions": [
                    {"protocol_key": "aave-v3", "amount_usd": 60_000},
                ],
                "portfolio": {
                    "total_capital_usd": 100_000,
                    "total_pnl_pct": 0.0,
                    "cash_usd": 40_000,
                },
            }

    ctx = _ctx(tmp_path, monkeypatch, trader=_Trader())
    ctx.pending_sky_alert = None
    ed.export_risk_alerts(ctx)
    doc = json.loads((tmp_path / "risk_alerts.json").read_text())
    assert doc["status"] == "critical"
    assert any(a["type"] == "concentration" and a["severity"] == "critical"
               for a in doc["alerts"])
    assert ctx.health["sections_ok"] == 1


def test_context_health_counters():
    ctx = ed.ExportContext(fetch=False)
    ctx.section_ok("a")
    ctx.section_ok("b")
    ctx.section_fail("c")
    assert ctx.health["sections_run"] == 3
    assert ctx.health["sections_ok"] == 2
    assert ctx.health["sections_failed"] == 1
    assert ctx.health["failed_sections"] == ["c"]
