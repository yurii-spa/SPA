"""
SPA Strategy-as-Config Validation Layer (Strategy Plane 1.1)
=============================================================

PARALLEL descriptor / change-control layer for SPA strategies.

This module treats each strategy as a *declarative, versioned config* — the
groundwork for change-control: changing a strategy = changing a validated
config whose hash is pinned. It does NOT replace the existing strategy classes
in ``spa_core/strategies/*`` — it *describes and validates* them. No existing
strategy module is touched.

NOTE on naming: ``strategy_config.py`` is already used (unrelated ADR-033
strategy-loop activation switch). This descriptor/validator layer lives in
``strategy_config_schema.py`` to avoid clobbering that module.

Why
---
Strategies today are hardcoded Python (StrategyMeta + handler class). For
change-control we want a flat, deterministic descriptor that:
  * can be schema-validated (default-deny on unknown / missing fields),
  * hashes to a stable sha256 (version pinning), and
  * can be derived best-effort from the existing heterogeneous REGISTRY so
    every current strategy gets a config view without a rewrite.

# LLM_FORBIDDEN — this is deterministic validation. No model calls, ever.

Schema (the strategy descriptor)
--------------------------------
    {
      "id":             str,            # registry id
      "version":        str,            # config version (string, e.g. "1.0")
      "tier_focus":     "T1"|"T2"|"T3", # dominant risk tier
      "target_apy_band":[lo, hi],       # ordered, lo <= hi, percent
      "max_protocols":  int >= 1,       # max concurrent positions
      "allocation_caps":{
          "per_protocol_max": float in [0,1],
          "t2_max":           float in [0,1],
          "cash_min":         float in [0,1],
      },
      "is_advisory":    bool,           # advisory / simulate-only
      "risk_profile":   "conservative"|"balanced"|"aggressive",
      "enabled":        bool,
    }

Constraints honoured: pure stdlib, deterministic, atomic writes (tmp +
shutil.move), parallel layer (only new files).

CLI:
    python3 -m spa_core.strategies.strategy_config_schema
        → prints how many registry strategies produced valid configs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ─── Paths ────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data"
_REPORT_PATH = _DATA_DIR / "strategy_configs.json"


# ─── Schema definition ─────────────────────────────────────────────────────────

VALID_TIER_FOCUS = {"T1", "T2", "T3"}
VALID_RISK_PROFILES = {"conservative", "balanced", "aggressive"}

# Top-level required fields and their expected python types.
REQUIRED_FIELDS: dict[str, Any] = {
    "id": str,
    "version": str,
    "tier_focus": str,
    "target_apy_band": (list, tuple),
    "max_protocols": int,
    "allocation_caps": dict,
    "is_advisory": bool,
    "risk_profile": str,
    "enabled": bool,
}

# Required keys inside allocation_caps; each must be a [0,1] fraction.
REQUIRED_CAP_KEYS = ("per_protocol_max", "t2_max", "cash_min")

# The exact set of allowed top-level keys (DEFAULT-DENY: anything else → invalid).
ALLOWED_TOP_LEVEL_KEYS = set(REQUIRED_FIELDS.keys())


# ─── Validation ────────────────────────────────────────────────────────────────

def _is_number(value: Any) -> bool:
    """True for real int/float (bool excluded — bool is a Number subtype)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_config(cfg: Any) -> dict:
    """
    Validate a strategy config descriptor against the schema.

    DEFAULT-DENY (Law 1 spirit): a config is invalid unless it positively
    satisfies every rule. Unknown top-level keys, missing required fields,
    out-of-range caps, reversed apy band, bad risk_profile, non-string
    version — all make the config invalid.

    Returns:
        {"valid": bool, "errors": [str, ...]}
    """
    errors: list[str] = []

    if not isinstance(cfg, dict):
        return {"valid": False, "errors": ["config must be a dict"]}

    # ── DEFAULT-DENY: reject unknown top-level keys ─────────────────────────────
    for key in cfg.keys():
        if key not in ALLOWED_TOP_LEVEL_KEYS:
            errors.append(f"unknown field '{key}' (default-deny)")

    # ── Required fields present and correctly typed ─────────────────────────────
    for field_name, expected_type in REQUIRED_FIELDS.items():
        if field_name not in cfg:
            errors.append(f"missing required field '{field_name}'")
            continue
        value = cfg[field_name]
        # bool is an int subclass — guard int fields against bool sneaking in.
        if expected_type is int and isinstance(value, bool):
            errors.append(f"field '{field_name}' must be int, got bool")
            continue
        if not isinstance(value, expected_type):
            errors.append(f"field '{field_name}' has wrong type")

    # Remaining value checks are individually guarded, so a missing field above
    # never crashes them.

    # ── tier_focus ──────────────────────────────────────────────────────────────
    tier = cfg.get("tier_focus")
    if tier is not None and tier not in VALID_TIER_FOCUS:
        errors.append(f"tier_focus '{tier}' not in {sorted(VALID_TIER_FOCUS)}")

    # ── risk_profile ──────────────────────────────────────────────────────────────
    profile = cfg.get("risk_profile")
    if profile is not None and profile not in VALID_RISK_PROFILES:
        errors.append(
            f"risk_profile '{profile}' not in {sorted(VALID_RISK_PROFILES)}"
        )

    # ── version must be a non-empty string ──────────────────────────────────────
    version = cfg.get("version")
    if version is not None:
        if not isinstance(version, str) or not version.strip():
            errors.append("version must be a non-empty string")

    # ── target_apy_band: [lo, hi], both numbers, ordered lo <= hi ───────────────
    band = cfg.get("target_apy_band")
    if band is not None:
        if not isinstance(band, (list, tuple)) or len(band) != 2:
            errors.append("target_apy_band must be a 2-element [lo, hi]")
        elif not (_is_number(band[0]) and _is_number(band[1])):
            errors.append("target_apy_band values must be numbers")
        elif band[0] > band[1]:
            errors.append(
                f"target_apy_band reversed: lo={band[0]} > hi={band[1]}"
            )

    # ── max_protocols >= 1 ────────────────────────────────────────────────────────
    max_protocols = cfg.get("max_protocols")
    if max_protocols is not None and not isinstance(max_protocols, bool):
        if isinstance(max_protocols, int) and max_protocols < 1:
            errors.append("max_protocols must be >= 1")

    # ── allocation_caps: required keys, each a [0,1] fraction ───────────────────
    caps = cfg.get("allocation_caps")
    if isinstance(caps, dict):
        for cap_key in caps.keys():
            if cap_key not in REQUIRED_CAP_KEYS:
                errors.append(
                    f"unknown allocation_caps key '{cap_key}' (default-deny)"
                )
        for cap_key in REQUIRED_CAP_KEYS:
            if cap_key not in caps:
                errors.append(f"allocation_caps missing '{cap_key}'")
                continue
            cap_val = caps[cap_key]
            if not _is_number(cap_val):
                errors.append(f"allocation_caps['{cap_key}'] must be a number")
            elif not (0.0 <= cap_val <= 1.0):
                errors.append(
                    f"allocation_caps['{cap_key}']={cap_val} out of [0,1]"
                )
    elif caps is not None:
        errors.append("allocation_caps must be a dict")

    return {"valid": len(errors) == 0, "errors": errors}


# ─── Derivation from existing registry ──────────────────────────────────────────

def _profile_from_tier(tier: str) -> str:
    """Map a risk tier to a risk_profile bucket (deterministic)."""
    return {
        "T1": "conservative",
        "T2": "balanced",
        "T3": "aggressive",
    }.get(tier, "balanced")


def _is_advisory_meta(meta: Any) -> bool:
    """
    Best-effort: detect whether a strategy is advisory / simulate-only.

    Looks at: tags containing 'advisory'/'research', or an IS_ADVISORY
    module-level constant on the handler module if importable. Defaults to
    False when nothing indicates advisory.
    """
    tags = [str(t).lower() for t in getattr(meta, "tags", []) or []]
    if any("advisory" in t or "research" in t for t in tags):
        return True
    # Try the implementing module's IS_ADVISORY constant (best-effort).
    module_path = getattr(meta, "module", "") or ""
    if module_path:
        try:
            import importlib

            mod = importlib.import_module(module_path)
            if bool(getattr(mod, "IS_ADVISORY", False)):
                return True
        except Exception:
            pass
    return False


def derive_config_from_registry(strategy_id: str) -> dict:
    """
    Best-effort derive a config descriptor for an existing registry strategy.

    Introspects the StrategyMeta in the live REGISTRY and produces a flat,
    schema-shaped config. Handles the heterogeneous registry gracefully:
    missing / absent attributes fall back to safe deterministic defaults.

    Raises:
        KeyError: if strategy_id is not present in the registry.
    """
    from spa_core.strategies.strategy_registry import REGISTRY

    meta = REGISTRY.get(strategy_id)
    if meta is None:
        raise KeyError(f"strategy '{strategy_id}' not found in REGISTRY")

    tier = getattr(meta, "risk_tier", "T2") or "T2"
    if tier not in VALID_TIER_FOCUS:
        tier = "T2"

    apy_min = float(getattr(meta, "target_apy_min", 0.0) or 0.0)
    apy_max = float(getattr(meta, "target_apy_max", 0.0) or 0.0)
    if apy_min > apy_max:  # defensive: keep band ordered for a valid descriptor
        apy_min, apy_max = apy_max, apy_min

    # Allocation caps mirror RiskPolicy v1.0 defaults, tier-aware.
    per_protocol_max = 0.40 if tier == "T1" else 0.20
    t2_max = 0.50
    cash_min = 0.05

    cfg = {
        "id": str(getattr(meta, "id", strategy_id)),
        "version": "1.0",
        "tier_focus": tier,
        "target_apy_band": [round(apy_min, 4), round(apy_max, 4)],
        "max_protocols": 8,  # ALLOC-002 portfolio cap, reused as descriptor max
        "allocation_caps": {
            "per_protocol_max": per_protocol_max,
            "t2_max": t2_max,
            "cash_min": cash_min,
        },
        "is_advisory": _is_advisory_meta(meta),
        "risk_profile": _profile_from_tier(tier),
        "enabled": bool(getattr(meta, "enabled", True)),
    }
    return cfg


def all_configs() -> list[dict]:
    """
    Return a config descriptor for every strategy in the live REGISTRY.

    Strategies whose derivation fails are skipped (logged), so a single
    malformed registry entry never breaks the whole view. Sorted by id for
    deterministic output.
    """
    from spa_core.strategies.strategy_registry import REGISTRY

    configs: list[dict] = []
    for strategy_id in sorted(REGISTRY.get_all(enabled_only=False).keys()):
        try:
            configs.append(derive_config_from_registry(strategy_id))
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("could not derive config for '%s': %s", strategy_id, exc)
    return configs


# ─── Change-control hashing ─────────────────────────────────────────────────────

def config_hash(cfg: dict) -> str:
    """
    Deterministic sha256 of a config (for change-control / version pinning).

    Uses canonical JSON (sorted keys, no insignificant whitespace) so two
    semantically equal configs always hash identically regardless of key order.
    """
    canonical = json.dumps(cfg, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ─── Report ──────────────────────────────────────────────────────────────────────

def _atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + shutil.move)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=False, default=str)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
    shutil.move(tmp, str(path))


def build_report(write: bool = True) -> dict:
    """
    Build the change-control report: every registry strategy as a config, with
    its validity and pinned hash.

    Writes data/strategy_configs.json atomically when ``write`` is True.

    Returns the report dict:
        {
          "schema_version": "1.1",
          "total": int,
          "valid_count": int,
          "invalid_count": int,
          "configs": [
              {"id", "config", "valid", "errors", "config_hash"}, ...
          ],
        }
    """
    configs = all_configs()
    entries: list[dict] = []
    valid_count = 0
    for cfg in configs:
        result = validate_config(cfg)
        if result["valid"]:
            valid_count += 1
        entries.append(
            {
                "id": cfg.get("id"),
                "config": cfg,
                "valid": result["valid"],
                "errors": result["errors"],
                "config_hash": config_hash(cfg),
            }
        )

    report = {
        "schema_version": "1.1",
        "total": len(entries),
        "valid_count": valid_count,
        "invalid_count": len(entries) - valid_count,
        "configs": entries,
    }

    if write:
        _atomic_write_json(_REPORT_PATH, report)
        log.info("wrote strategy config report → %s", _REPORT_PATH)

    return report


# ─── CLI ───────────────────────────────────────────────────────────────────────

def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report = build_report(write=True)
    print(
        f"strategy-as-config: {report['valid_count']}/{report['total']} "
        f"registry strategies produced valid configs "
        f"({report['invalid_count']} invalid)"
    )
    print(f"report → {_REPORT_PATH}")


if __name__ == "__main__":
    _main()
