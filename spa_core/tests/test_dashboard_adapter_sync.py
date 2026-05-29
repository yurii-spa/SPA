"""
Contract tests between the backend source of truth (data/adapter_status.json)
and what the Go-Live dashboard front-end (index.html) expects (Sprint SPA-V334).

The front-end now fetches data/adapter_status.json and renders it via
mapAdapterRecord() with a graceful fallback to the embedded ADAPTER_STATUS_FALLBACK
constant.  These tests pin the JSON contract and re-implement the transformer in
Python so a backend field rename can never silently break the dashboard.

All tests are deterministic and network-free.
"""
import json
import math
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_JSON_PATH = _REPO_ROOT / "data" / "adapter_status.json"
_INDEX_HTML = _REPO_ROOT / "index.html"

EXPECTED_PROTOCOL_KEYS = ["yearn-v3", "euler-v2", "maple", "pendle-pt", "sky-susds"]

# Fields the front-end transformer (mapAdapterRecord) reads off every record.
REQUIRED_FIELDS = (
    "protocol_key",
    "name",
    "tier",
    "allocation_cap",
    "chains",
    "assets",
    "mock_apy",
    "write_state",
    "apy_source",
)

# Verbatim expected values (read from the actual JSON, not guessed).
EXPECTED_ALLOCATION_CAP = {
    "yearn-v3": 0.2,
    "euler-v2": 0.2,
    "maple": 0.2,
    "pendle-pt": 0.2,
    "sky-susds": 0.0,
}
EXPECTED_WRITE_STATE = {
    "yearn-v3": "BLOCKED",
    "euler-v2": "BLOCKED",
    "maple": "BLOCKED",
    "pendle-pt": "NOT_IMPLEMENTED",
    "sky-susds": "BLOCKED",
}


@pytest.fixture(scope="module")
def doc():
    assert _JSON_PATH.exists(), f"missing artifact: {_JSON_PATH}"
    with open(_JSON_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def by_key(doc):
    return {a["protocol_key"]: a for a in doc["adapters"]}


# ─── Document-level contract ─────────────────────────────────────────────────

class TestDocument:
    def test_json_loads(self, doc):
        assert isinstance(doc, dict)

    def test_schema_version(self, doc):
        assert doc["schema_version"] == 1

    def test_exactly_five_adapters(self, doc):
        assert len(doc["adapters"]) == 5

    def test_protocol_keys(self, doc):
        keys = [a["protocol_key"] for a in doc["adapters"]]
        assert keys == EXPECTED_PROTOCOL_KEYS

    def test_has_top_level_fields(self, doc):
        for field in ("generated_at", "schema_version", "execution_mode", "live_apy_enabled", "adapters"):
            assert field in doc, f"document missing {field}"

    def test_live_apy_enabled_is_bool(self, doc):
        assert isinstance(doc["live_apy_enabled"], bool)


# ─── Per-adapter required fields / types ─────────────────────────────────────

class TestRequiredFields:
    @pytest.mark.parametrize("key", EXPECTED_PROTOCOL_KEYS)
    def test_required_fields_present(self, by_key, key):
        rec = by_key[key]
        for field in REQUIRED_FIELDS:
            assert field in rec, f"{key} missing {field}"

    @pytest.mark.parametrize("key", EXPECTED_PROTOCOL_KEYS)
    def test_field_types(self, by_key, key):
        rec = by_key[key]
        assert isinstance(rec["protocol_key"], str)
        assert isinstance(rec["name"], str) and rec["name"]
        assert isinstance(rec["tier"], str) and rec["tier"]
        assert isinstance(rec["allocation_cap"], float)
        assert isinstance(rec["chains"], list) and rec["chains"]
        assert isinstance(rec["assets"], list) and rec["assets"]
        assert isinstance(rec["mock_apy"], dict) and rec["mock_apy"]
        assert isinstance(rec["write_state"], str) and rec["write_state"]
        assert isinstance(rec["apy_source"], dict)

    @pytest.mark.parametrize("key", EXPECTED_PROTOCOL_KEYS)
    def test_apy_source_shape(self, by_key, key):
        src = by_key[key]["apy_source"]
        assert "mode" in src and isinstance(src["mode"], str)
        assert "live_project" in src and isinstance(src["live_project"], str)
        assert "live_enabled" in src and isinstance(src["live_enabled"], bool)


# ─── Verbatim values ─────────────────────────────────────────────────────────

class TestVerbatimValues:
    @pytest.mark.parametrize("key", EXPECTED_PROTOCOL_KEYS)
    def test_allocation_cap(self, by_key, key):
        assert math.isclose(by_key[key]["allocation_cap"], EXPECTED_ALLOCATION_CAP[key])

    @pytest.mark.parametrize("key", EXPECTED_PROTOCOL_KEYS)
    def test_write_state(self, by_key, key):
        assert by_key[key]["write_state"] == EXPECTED_WRITE_STATE[key]

    def test_sky_cap_is_zero(self, by_key):
        assert by_key["sky-susds"]["allocation_cap"] == 0.0

    def test_pendle_not_implemented(self, by_key):
        assert by_key["pendle-pt"]["write_state"] == "NOT_IMPLEMENTED"


# ─── Transformer parity (Python mirror of index.html mapAdapterRecord) ───────

def _map_adapter_record(rec):
    """Mirror of the JS mapAdapterRecord() in index.html."""
    cap = f"{round(rec.get('allocation_cap', 0) * 100)}%"
    mock = rec.get("mock_apy") or {}
    chain_keys = list(mock.keys())
    apy_lines = []
    for ch in chain_keys:
        pairs = " / ".join(f"{asset} {mock[ch][asset]}%" for asset in mock[ch])
        apy_lines.append(f"{ch[:3].upper()}: {pairs}" if len(chain_keys) > 1 else pairs)
    apy = "<br>".join(apy_lines)
    src = rec.get("apy_source") or {}
    write_state = rec.get("write_state")
    if write_state == "BLOCKED":
        state, label, note = "blocked", "Writes BLOCKED", "Phase 3 · SPA_EXECUTION_MODE≠live"
    elif write_state == "NOT_IMPLEMENTED":
        state, label, note = "notimpl", "Writes NOT_IMPLEMENTED", "Phase 3"
    else:
        state, label, note = "ok", str(write_state or "OK"), ""
    return {
        "name": rec["name"],
        "tier": rec["tier"],
        "cap": cap,
        "capNote": rec.get("allocation_note", ""),
        "chains": ", ".join(rec.get("chains", [])),
        "assets": " / ".join(rec.get("assets", [])),
        "apy": apy,
        "source": src.get("mode"),
        "project": src.get("live_project"),
        "liveEnabled": bool(src.get("live_enabled")),
        "state": state,
        "stateLabel": label,
        "stateNote": note,
    }


class TestTransformerParity:
    def test_cap_formatting(self):
        assert _map_adapter_record({"name": "x", "tier": "T2", "allocation_cap": 0.2,
                                     "chains": [], "assets": [], "apy_source": {}})["cap"] == "20%"
        assert _map_adapter_record({"name": "x", "tier": "T2", "allocation_cap": 0.0,
                                     "chains": [], "assets": [], "apy_source": {}})["cap"] == "0%"

    @pytest.mark.parametrize("key", EXPECTED_PROTOCOL_KEYS)
    def test_mapped_fields_nonempty_strings(self, by_key, key):
        mapped = _map_adapter_record(by_key[key])
        for field in ("name", "tier", "cap", "chains", "assets", "apy", "source", "project",
                      "state", "stateLabel"):
            assert isinstance(mapped[field], str), f"{key}.{field} not str"
            assert mapped[field] != "", f"{key}.{field} empty"

    def test_chains_and_assets_join(self, by_key):
        m = _map_adapter_record(by_key["yearn-v3"])
        assert m["chains"] == "ethereum, arbitrum"
        assert m["assets"] == "USDC / USDT"

    @pytest.mark.parametrize("key", EXPECTED_PROTOCOL_KEYS)
    def test_state_mapping(self, by_key, key):
        m = _map_adapter_record(by_key[key])
        expected = {"BLOCKED": "blocked", "NOT_IMPLEMENTED": "notimpl"}[EXPECTED_WRITE_STATE[key]]
        assert m["state"] == expected


# ─── Front-end wiring guard (index.html edits are in place) ──────────────────

class TestFrontEndWiring:
    @pytest.fixture(scope="class")
    def html(self):
        assert _INDEX_HTML.exists(), f"missing {_INDEX_HTML}"
        return _INDEX_HTML.read_text(encoding="utf-8")

    @pytest.mark.parametrize("token", [
        "loadAdapterStatus",
        "ADAPTER_STATUS_FALLBACK",
        "mapAdapterRecord",
        "adapter_status.json",
    ])
    def test_token_present(self, html, token):
        assert token in html, f"index.html missing expected token: {token}"

    def test_old_constant_renamed(self, html):
        # The bare hardcoded constant must be gone (renamed to *_FALLBACK).
        assert "const ADAPTER_STATUS =" not in html
