"""
Tests for the strategy-as-config validation layer (Strategy Plane 1.1).

Target module: spa_core.strategies.strategy_config_schema

Covers:
  * a well-formed config passes validation,
  * DEFAULT-DENY: missing required field → invalid,
  * caps out of [0,1] → invalid,
  * reversed apy band → invalid,
  * config_hash is deterministic and changes when the config changes,
  * derive_config_from_registry returns a dict for a known strategy,
  * build_report has the documented structure.

Pure stdlib, deterministic. # LLM_FORBIDDEN
"""

from __future__ import annotations

import copy

from spa_core.strategies import strategy_config_schema as scs


# ─── A canonical valid config used as the baseline for mutations ────────────────

def _valid_config() -> dict:
    return {
        "id": "s_test_strategy",
        "version": "1.0",
        "tier_focus": "T1",
        "target_apy_band": [4.0, 6.0],
        "max_protocols": 5,
        "allocation_caps": {
            "per_protocol_max": 0.40,
            "t2_max": 0.50,
            "cash_min": 0.05,
        },
        "is_advisory": False,
        "risk_profile": "conservative",
        "enabled": True,
    }


# ─── Happy path ─────────────────────────────────────────────────────────────────

def test_valid_config_passes():
    result = scs.validate_config(_valid_config())
    assert result["valid"] is True, result["errors"]
    assert result["errors"] == []


# ─── DEFAULT-DENY: missing required field ───────────────────────────────────────

def test_missing_required_field_is_invalid():
    cfg = _valid_config()
    del cfg["risk_profile"]
    result = scs.validate_config(cfg)
    assert result["valid"] is False
    assert any("risk_profile" in e for e in result["errors"])


def test_unknown_field_is_invalid_default_deny():
    cfg = _valid_config()
    cfg["sneaky_extra"] = 123
    result = scs.validate_config(cfg)
    assert result["valid"] is False
    assert any("sneaky_extra" in e for e in result["errors"])


def test_non_dict_is_invalid():
    assert scs.validate_config(None)["valid"] is False
    assert scs.validate_config("not a dict")["valid"] is False
    assert scs.validate_config([1, 2, 3])["valid"] is False


# ─── Caps out of [0,1] ──────────────────────────────────────────────────────────

def test_caps_out_of_range_is_invalid():
    cfg = _valid_config()
    cfg["allocation_caps"]["per_protocol_max"] = 1.5
    result = scs.validate_config(cfg)
    assert result["valid"] is False
    assert any("per_protocol_max" in e for e in result["errors"])


def test_negative_cap_is_invalid():
    cfg = _valid_config()
    cfg["allocation_caps"]["cash_min"] = -0.01
    result = scs.validate_config(cfg)
    assert result["valid"] is False
    assert any("cash_min" in e for e in result["errors"])


def test_missing_cap_key_is_invalid():
    cfg = _valid_config()
    del cfg["allocation_caps"]["t2_max"]
    result = scs.validate_config(cfg)
    assert result["valid"] is False
    assert any("t2_max" in e for e in result["errors"])


# ─── APY band ordering ──────────────────────────────────────────────────────────

def test_apy_band_reversed_is_invalid():
    cfg = _valid_config()
    cfg["target_apy_band"] = [6.0, 4.0]  # lo > hi
    result = scs.validate_config(cfg)
    assert result["valid"] is False
    assert any("reversed" in e for e in result["errors"])


def test_apy_band_equal_endpoints_is_valid():
    cfg = _valid_config()
    cfg["target_apy_band"] = [5.0, 5.0]  # lo == hi is allowed
    assert scs.validate_config(cfg)["valid"] is True


# ─── risk_profile / version / tier ──────────────────────────────────────────────

def test_bad_risk_profile_is_invalid():
    cfg = _valid_config()
    cfg["risk_profile"] = "reckless"
    result = scs.validate_config(cfg)
    assert result["valid"] is False


def test_non_string_version_is_invalid():
    cfg = _valid_config()
    cfg["version"] = 1.0  # number, not a string
    result = scs.validate_config(cfg)
    assert result["valid"] is False
    assert any("version" in e for e in result["errors"])


def test_bad_tier_focus_is_invalid():
    cfg = _valid_config()
    cfg["tier_focus"] = "T9"
    assert scs.validate_config(cfg)["valid"] is False


# ─── config_hash determinism & sensitivity ──────────────────────────────────────

def test_config_hash_deterministic():
    cfg = _valid_config()
    h1 = scs.config_hash(cfg)
    h2 = scs.config_hash(copy.deepcopy(cfg))
    assert h1 == h2
    assert isinstance(h1, str) and len(h1) == 64  # sha256 hexdigest


def test_config_hash_key_order_independent():
    cfg = _valid_config()
    reordered = {k: cfg[k] for k in reversed(list(cfg.keys()))}
    assert scs.config_hash(cfg) == scs.config_hash(reordered)


def test_config_hash_changes_when_config_changes():
    cfg = _valid_config()
    before = scs.config_hash(cfg)
    cfg["version"] = "1.1"
    after = scs.config_hash(cfg)
    assert before != after


# ─── derive_config_from_registry ────────────────────────────────────────────────

def test_derive_config_from_registry_returns_valid_dict():
    # Ensure the registry is populated (importing it triggers self-registration).
    from spa_core.strategies.strategy_registry import REGISTRY

    all_ids = list(REGISTRY.get_all(enabled_only=False).keys())
    assert all_ids, "registry should have at least one strategy"

    known_id = (
        "s1_conservative_lending"
        if "s1_conservative_lending" in all_ids
        else all_ids[0]
    )
    cfg = scs.derive_config_from_registry(known_id)
    assert isinstance(cfg, dict)
    assert cfg["id"] == known_id
    # A derived config must itself be schema-valid.
    result = scs.validate_config(cfg)
    assert result["valid"] is True, result["errors"]


def test_derive_unknown_strategy_raises():
    import pytest

    with pytest.raises(KeyError):
        scs.derive_config_from_registry("definitely_not_a_real_strategy_id")


# ─── all_configs & build_report structure ───────────────────────────────────────

def test_all_configs_returns_list_of_dicts():
    configs = scs.all_configs()
    assert isinstance(configs, list)
    assert configs, "expected at least one derived config"
    assert all(isinstance(c, dict) for c in configs)


def test_build_report_structure():
    report = scs.build_report(write=False)
    assert set(
        ["schema_version", "total", "valid_count", "invalid_count", "configs"]
    ).issubset(report.keys())
    assert report["total"] == len(report["configs"])
    assert report["valid_count"] + report["invalid_count"] == report["total"]
    for entry in report["configs"]:
        assert set(["id", "config", "valid", "errors", "config_hash"]).issubset(
            entry.keys()
        )
        assert isinstance(entry["config_hash"], str)
        assert len(entry["config_hash"]) == 64
        # The recorded hash must match recomputing it from the config.
        assert entry["config_hash"] == scs.config_hash(entry["config"])


def test_build_report_writes_file(tmp_path, monkeypatch):
    # Redirect the report path to a temp file so the test is hermetic.
    out = tmp_path / "strategy_configs.json"
    monkeypatch.setattr(scs, "_REPORT_PATH", out)
    report = scs.build_report(write=True)
    assert out.exists()
    import json

    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk["total"] == report["total"]
