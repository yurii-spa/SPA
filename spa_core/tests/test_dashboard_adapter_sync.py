"""
Contract tests between the backend source of truth (data/adapter_status.json)
and what the Go-Live dashboard front-end (index.html) expects.

Originally written for Sprint SPA-V334 (5 adapters); updated in SPA-V416 to
the current 7-adapter reality (aave-v3 + compound-v3 were added to the
registry / artifact on 2026-05-31). The invariant is unchanged: the dashboard
fetches data/adapter_status.json and renders it via mapAdapterRecord(), so a
backend field rename or registry/artifact drift must never silently break the
dashboard. To avoid pinning a stale hardcoded list ever again, the expected
protocol keys are *derived* from the code registry
(spa_core/execution/adapter_status.py :: _ADAPTER_SPECS) via a read-only AST
parse — the artifact must match the registry, and the dashboard transformer
must handle every registry record.

Converted pytest -> unittest in SPA-V416 (pytest is not installed in this
repo; under `python3 -m unittest` the old file was red with
ModuleNotFoundError: pytest). All tests are deterministic and network-free;
the execution/ domain is only READ (AST on source text), never imported or
modified (SPA-BL-011).

Run::

    python3 -m unittest spa_core.tests.test_dashboard_adapter_sync
"""
import ast
import json
import math
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_JSON_PATH = _REPO_ROOT / "data" / "adapter_status.json"
_INDEX_HTML = _REPO_ROOT / "index.html"
_REGISTRY_PY = _REPO_ROOT / "spa_core" / "execution" / "adapter_status.py"

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

# Verbatim expected values for the current 7-adapter registry (read from the
# actual artifact/registry as of 2026-05-31, not guessed).
EXPECTED_ADAPTER_COUNT = 7
EXPECTED_ALLOCATION_CAP = {
    "aave-v3": 0.4,
    "compound-v3": 0.4,
    "yearn-v3": 0.2,
    "euler-v2": 0.2,
    "maple": 0.2,
    "pendle-pt": 0.2,
    "sky-susds": 0.0,
}
EXPECTED_WRITE_STATE = {
    "aave-v3": "BLOCKED",
    "compound-v3": "BLOCKED",
    "yearn-v3": "BLOCKED",
    "euler-v2": "BLOCKED",
    "maple": "BLOCKED",
    "pendle-pt": "NOT_IMPLEMENTED",
    "sky-susds": "BLOCKED",
}


def _registry_protocol_keys():
    """Read-only AST extraction of protocol_key values from _ADAPTER_SPECS.

    Parses spa_core/execution/adapter_status.py WITHOUT importing it (the
    execution domain is never executed by this test) and returns the
    protocol_key of every spec, in registry order.
    """
    tree = ast.parse(_REGISTRY_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if "_ADAPTER_SPECS" not in names or node.value is None:
                continue
            keys = []
            for elt in node.value.elts:  # list of dict literals
                for k, v in zip(elt.keys, elt.values):
                    if (isinstance(k, ast.Constant) and k.value == "protocol_key"
                            and isinstance(v, ast.Constant)):
                        keys.append(v.value)
            return keys
    raise AssertionError(f"_ADAPTER_SPECS not found in {_REGISTRY_PY}")


def _load_doc():
    assert _JSON_PATH.exists(), f"missing artifact: {_JSON_PATH}"
    with open(_JSON_PATH, encoding="utf-8") as fh:
        return json.load(fh)


_DOC = _load_doc()
_BY_KEY = {a["protocol_key"]: a for a in _DOC["adapters"]}
_REGISTRY_KEYS = _registry_protocol_keys()


# ─── Document-level contract ─────────────────────────────────────────────────

class TestDocument(unittest.TestCase):
    def test_json_loads(self):
        self.assertIsInstance(_DOC, dict)

    def test_schema_version(self):
        self.assertEqual(_DOC["schema_version"], 1)

    def test_adapter_count_matches_registry(self):
        self.assertEqual(len(_REGISTRY_KEYS), EXPECTED_ADAPTER_COUNT)
        self.assertEqual(len(_DOC["adapters"]), len(_REGISTRY_KEYS))

    def test_protocol_keys_match_registry_order(self):
        keys = [a["protocol_key"] for a in _DOC["adapters"]]
        self.assertEqual(keys, _REGISTRY_KEYS)

    def test_expected_value_maps_cover_registry(self):
        # the pinned verbatim maps must stay in lockstep with the registry
        self.assertEqual(sorted(EXPECTED_ALLOCATION_CAP), sorted(_REGISTRY_KEYS))
        self.assertEqual(sorted(EXPECTED_WRITE_STATE), sorted(_REGISTRY_KEYS))

    def test_has_top_level_fields(self):
        for field in ("generated_at", "schema_version", "execution_mode",
                      "live_apy_enabled", "adapters"):
            self.assertIn(field, _DOC, f"document missing {field}")

    def test_live_apy_enabled_is_bool(self):
        self.assertIsInstance(_DOC["live_apy_enabled"], bool)


# ─── Per-adapter required fields / types ─────────────────────────────────────

class TestRequiredFields(unittest.TestCase):
    def test_required_fields_present(self):
        for key in _REGISTRY_KEYS:
            rec = _BY_KEY[key]
            for field in REQUIRED_FIELDS:
                self.assertIn(field, rec, f"{key} missing {field}")

    def test_field_types(self):
        for key in _REGISTRY_KEYS:
            with self.subTest(key=key):
                rec = _BY_KEY[key]
                self.assertIsInstance(rec["protocol_key"], str)
                self.assertIsInstance(rec["name"], str)
                self.assertTrue(rec["name"])
                self.assertIsInstance(rec["tier"], str)
                self.assertTrue(rec["tier"])
                self.assertIsInstance(rec["allocation_cap"], float)
                self.assertIsInstance(rec["chains"], list)
                self.assertTrue(rec["chains"])
                self.assertIsInstance(rec["assets"], list)
                self.assertTrue(rec["assets"])
                self.assertIsInstance(rec["mock_apy"], dict)
                self.assertTrue(rec["mock_apy"])
                self.assertIsInstance(rec["write_state"], str)
                self.assertTrue(rec["write_state"])
                self.assertIsInstance(rec["apy_source"], dict)

    def test_apy_source_shape(self):
        for key in _REGISTRY_KEYS:
            with self.subTest(key=key):
                src = _BY_KEY[key]["apy_source"]
                self.assertIn("mode", src)
                self.assertIsInstance(src["mode"], str)
                self.assertIn("live_project", src)
                self.assertIsInstance(src["live_project"], str)
                self.assertIn("live_enabled", src)
                self.assertIsInstance(src["live_enabled"], bool)


# ─── Verbatim values ─────────────────────────────────────────────────────────

class TestVerbatimValues(unittest.TestCase):
    def test_allocation_cap(self):
        for key in _REGISTRY_KEYS:
            with self.subTest(key=key):
                self.assertTrue(math.isclose(
                    _BY_KEY[key]["allocation_cap"], EXPECTED_ALLOCATION_CAP[key]))

    def test_write_state(self):
        for key in _REGISTRY_KEYS:
            with self.subTest(key=key):
                self.assertEqual(_BY_KEY[key]["write_state"],
                                 EXPECTED_WRITE_STATE[key])

    def test_t1_caps_are_forty_percent(self):
        for key in ("aave-v3", "compound-v3"):
            self.assertEqual(_BY_KEY[key]["tier"], "T1")
            self.assertTrue(math.isclose(_BY_KEY[key]["allocation_cap"], 0.4))

    def test_sky_cap_is_zero(self):
        self.assertEqual(_BY_KEY["sky-susds"]["allocation_cap"], 0.0)

    def test_pendle_not_implemented(self):
        self.assertEqual(_BY_KEY["pendle-pt"]["write_state"], "NOT_IMPLEMENTED")


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


class TestTransformerParity(unittest.TestCase):
    def test_cap_formatting(self):
        self.assertEqual(
            _map_adapter_record({"name": "x", "tier": "T2", "allocation_cap": 0.2,
                                 "chains": [], "assets": [], "apy_source": {}})["cap"],
            "20%")
        self.assertEqual(
            _map_adapter_record({"name": "x", "tier": "T1", "allocation_cap": 0.4,
                                 "chains": [], "assets": [], "apy_source": {}})["cap"],
            "40%")
        self.assertEqual(
            _map_adapter_record({"name": "x", "tier": "T2", "allocation_cap": 0.0,
                                 "chains": [], "assets": [], "apy_source": {}})["cap"],
            "0%")

    def test_mapped_fields_nonempty_strings(self):
        for key in _REGISTRY_KEYS:
            with self.subTest(key=key):
                mapped = _map_adapter_record(_BY_KEY[key])
                for field in ("name", "tier", "cap", "chains", "assets", "apy",
                              "source", "project", "state", "stateLabel"):
                    self.assertIsInstance(mapped[field], str, f"{key}.{field} not str")
                    self.assertNotEqual(mapped[field], "", f"{key}.{field} empty")

    def test_chains_and_assets_join(self):
        m = _map_adapter_record(_BY_KEY["yearn-v3"])
        self.assertEqual(m["chains"], "ethereum, arbitrum")
        self.assertEqual(m["assets"], "USDC / USDT")
        m1 = _map_adapter_record(_BY_KEY["aave-v3"])
        self.assertEqual(m1["chains"], "ethereum, arbitrum, base")
        self.assertEqual(m1["assets"], "USDC / USDT / DAI")

    def test_state_mapping(self):
        for key in _REGISTRY_KEYS:
            with self.subTest(key=key):
                m = _map_adapter_record(_BY_KEY[key])
                expected = {"BLOCKED": "blocked",
                            "NOT_IMPLEMENTED": "notimpl"}[EXPECTED_WRITE_STATE[key]]
                self.assertEqual(m["state"], expected)


# ─── Front-end wiring guard (index.html edits are in place) ──────────────────

class TestFrontEndWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert _INDEX_HTML.exists(), f"missing {_INDEX_HTML}"
        cls.html = _INDEX_HTML.read_text(encoding="utf-8")

    def test_token_present(self):
        for token in ("loadAdapterStatus", "ADAPTER_STATUS_FALLBACK",
                      "mapAdapterRecord", "adapter_status.json"):
            with self.subTest(token=token):
                self.assertIn(token, self.html,
                              f"index.html missing expected token: {token}")

    def test_old_constant_renamed(self):
        # The bare hardcoded constant must be gone (renamed to *_FALLBACK).
        self.assertNotIn("const ADAPTER_STATUS =", self.html)

    def test_live_apy_wiring_present(self):
        # v3.35 — live APY rendering wiring.
        for token in ("fmtApyMap",          # shared chain→asset→apy formatter
                      "apyLive",            # mapped live-APY HTML string
                      "rec.live_apy",       # reads the backend-embedded live values
                      "liveValuesPresent",  # mapped from apy_source.live_values_present
                      "apyCell"):           # APY cell prefers live values when present
            with self.subTest(token=token):
                self.assertIn(token, self.html,
                              f"index.html missing v3.35 live-APY token: {token}")


if __name__ == "__main__":
    unittest.main()
