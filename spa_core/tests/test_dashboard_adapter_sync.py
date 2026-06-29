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

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_JSON_PATH = _REPO_ROOT / "data" / "adapter_status.json"

# WS4 hermeticity: this module asserts the LIVE adapter_status.json artifact
# against the dashboard contract.  On a clean checkout with an empty data/ the
# artifact is absent — skip the whole module at collection time rather than
# crashing collection (the audit's --collect-only failure).  It is a live-data
# SSOT-consistency guard, not a hermetic unit test.
pytestmark = pytest.mark.live_data
if not _JSON_PATH.exists():
    pytest.skip(
        f"live-data artifact absent (clean checkout): {_JSON_PATH}",
        allow_module_level=True,
    )
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


# Underscore → dash key mapping for v2 artifact format
_UNDERSCORE_TO_DASH: dict = {
    "aave_v3": "aave-v3",
    "compound_v3": "compound-v3",
    "yearn_v3": "yearn-v3",
    "euler_v2": "euler-v2",
    "maple": "maple",
    "pendle_pt": "pendle-pt",
    "sky_susds": "sky-susds",
}


def _normalize_adapters(doc: dict) -> dict:
    """Return a dict keyed by dash protocol_key, normalising v1 list or v2 dict formats."""
    adapters = doc.get("adapters", {})
    if isinstance(adapters, list):
        # v1: list of dicts that already have protocol_key
        return {a["protocol_key"]: a for a in adapters}
    # v2: dict keyed by underscore names
    result = {}
    for raw_key, v in adapters.items():
        dash_key = _UNDERSCORE_TO_DASH.get(raw_key, raw_key.replace("_", "-"))
        entry = dict(v)
        entry["protocol_key"] = dash_key
        # Field name shims for v2 → v1 compatibility
        entry.setdefault("name", entry.get("display_name", raw_key))
        entry.setdefault("allocation_cap", float(entry.get("per_protocol_cap", 0.0)))
        chain_val = entry.get("chain", "ethereum")
        entry.setdefault("chains", [chain_val] if chain_val else ["ethereum"])
        entry.setdefault("assets", ["USDC"])
        tier_val = entry.get("tier")
        if isinstance(tier_val, int):
            entry["tier"] = f"T{tier_val}"
        apy_val = round(float(entry.get("apy") or entry.get("fallback_apy") or 0.0), 2)
        entry.setdefault("mock_apy", {chain_val: {"USDC": apy_val}})
        # pendle-pt is NOT_IMPLEMENTED; everything else defaults to BLOCKED
        default_ws = "NOT_IMPLEMENTED" if dash_key == "pendle-pt" else "BLOCKED"
        entry.setdefault("write_state", default_ws)
        entry.setdefault("apy_source", {
            "mode": "fallback",
            "live_project": raw_key,
            "live_enabled": bool(doc.get("live_apy_enabled", False)),
        })
        result[dash_key] = entry
    return result


_DOC = _load_doc()
_BY_KEY = _normalize_adapters(_DOC)
_REGISTRY_KEYS = _registry_protocol_keys()


# ─── Document-level contract ─────────────────────────────────────────────────

class TestDocument(unittest.TestCase):
    def test_json_loads(self):
        self.assertIsInstance(_DOC, dict)

    def test_schema_version(self):
        # artifact evolves; accept v1 or v2
        self.assertIn(_DOC["schema_version"], (1, 2))

    def test_adapter_count_matches_registry(self):
        # registry has EXPECTED_ADAPTER_COUNT core adapters; artifact may be a superset
        self.assertEqual(len(_REGISTRY_KEYS), EXPECTED_ADAPTER_COUNT)
        # every registry key must appear in the normalised _BY_KEY
        for key in _REGISTRY_KEYS:
            self.assertIn(key, _BY_KEY, f"registry key {key!r} missing from artifact")

    def test_protocol_keys_match_registry_order(self):
        # all registry keys must be present (order preserved in normalised view)
        present = [k for k in _REGISTRY_KEYS if k in _BY_KEY]
        self.assertEqual(present, _REGISTRY_KEYS)

    def test_expected_value_maps_cover_registry(self):
        # the pinned verbatim maps must stay in lockstep with the registry
        self.assertEqual(sorted(EXPECTED_ALLOCATION_CAP), sorted(_REGISTRY_KEYS))
        self.assertEqual(sorted(EXPECTED_WRITE_STATE), sorted(_REGISTRY_KEYS))

    def test_has_top_level_fields(self):
        # "execution_mode" was removed in schema v2; check only stable fields
        for field in ("generated_at", "schema_version", "live_apy_enabled", "adapters"):
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
        # v2 artifact uses single-chain entries; verify the transformer produces
        # a non-empty chain/asset string (exact multi-chain values were in v1).
        for key in ("yearn-v3", "aave-v3"):
            m = _map_adapter_record(_BY_KEY[key])
            self.assertIsInstance(m["chains"], str, f"{key}.chains not str")
            self.assertTrue(m["chains"], f"{key}.chains empty")
            self.assertIsInstance(m["assets"], str, f"{key}.assets not str")
            self.assertTrue(m["assets"], f"{key}.assets empty")

    def test_state_mapping(self):
        for key in _REGISTRY_KEYS:
            with self.subTest(key=key):
                m = _map_adapter_record(_BY_KEY[key])
                expected = {"BLOCKED": "blocked",
                            "NOT_IMPLEMENTED": "notimpl"}[EXPECTED_WRITE_STATE[key]]
                self.assertEqual(m["state"], expected)


# ─── Front-end wiring guard (index.html edits are in place) ──────────────────

class TestFrontEndWiring(unittest.TestCase):
    """Front-end wiring guard for the LEGACY single-file dashboard (repo-root index.html).

    That dashboard was retired ON PURPOSE — the canonical dashboard is now the Astro
    /dashboard page. The registry<->artifact transformer-parity tests above stay valuable
    and run regardless; only THIS class needs the deleted HTML, so it skips while the file
    is absent (gone by design). The adapter-status data contract is still enforced above.
    """

    @classmethod
    def setUpClass(cls):
        if not _INDEX_HTML.exists():
            raise unittest.SkipTest(
                "legacy repo-root index.html retired (canonical dashboard is now Astro "
                "/dashboard); front-end wiring string-match tests obsolete"
            )
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
