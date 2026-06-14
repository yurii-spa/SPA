"""Manifest schema + loader for declarative adapters (SPA-V417 / MP-204).

A manifest is a small YAML (or JSON — same schema) document describing one
protocol on top of DeFiLlama identifiers::

    name: spark                      # required — unique adapter/protocol key
    defillama_protocol_id: spark     # required — DeFiLlama project slug
    chains: [Ethereum]               # optional, default [Ethereum]
    symbols: [USDC, DAI]             # optional, default [USDC]
    pool_ids: []                     # optional explicit DeFiLlama pool uuids
    tier: T2                         # required — T1 / T2 / T3
    cap: 0.20                        # optional, default by tier (T1 .40/T2 .20/T3 .10)
    exit_latency:                    # optional (SPA-V412-style profile)
      hours: 0.0                     #   None == undeclared (treated illiquid)
      profile: instant               #   default derived from hours
    quality_gates:                   # optional
      min_tvl_usd: 1000000           #   >= 0; default 100_000 (feed liveness floor)
      stable_only: true              #   reject non-stablecoin symbols
      max_apy_pct: 30.0              #   reject implausibly high APY (percent)

Validation is collected, not fail-fast: every problem is gathered and raised
as one :class:`ValidationError` carrying ``problems: list[str]`` — callers see
a readable list ("missing required field 'name'", "unknown tier 'T9' ..."),
never a bare stacktrace.

YAML is parsed with PyYAML when available. Graceful fallback: if PyYAML is not
installed, ``.json`` manifests work unchanged, and a ``.yaml`` file whose body
happens to be valid JSON (JSON is a YAML subset) is still accepted.

Pure stdlib + optional PyYAML; no network, no writes. STRICTLY READ-ONLY.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .contract import DEFAULT_TIER_CAPS, VALID_TIERS

try:  # graceful: PyYAML is optional — JSON manifests keep working without it.
    import yaml  # type: ignore
except Exception:  # pragma: no cover - exercised via monkeypatch in tests
    yaml = None  # type: ignore

# Exit-latency bucket boundary — mirrors exit_latency_policy.ILLIQUID_THRESHOLD_HOURS
# (kept as a literal so this module stays importable without the adapters pkg).
ILLIQUID_THRESHOLD_HOURS: float = 72.0

# Default liveness floor — mirrors defillama_feed.MIN_TVL_USD_DEFAULT.
DEFAULT_MIN_TVL_USD: float = 100_000.0

MANIFEST_SUFFIXES = (".yaml", ".yml", ".json")


class ValidationError(ValueError):
    """Manifest failed validation. ``problems`` lists every issue found."""

    def __init__(self, source: str, problems: List[str]):
        self.source = str(source)
        self.problems = list(problems)
        msg = f"invalid manifest {self.source}: " + "; ".join(self.problems)
        super().__init__(msg)


@dataclass(frozen=True)
class QualityGates:
    """Per-manifest pool quality gates (all advisory filters, read-only)."""

    min_tvl_usd: float = DEFAULT_MIN_TVL_USD
    stable_only: bool = False
    max_apy_pct: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "min_tvl_usd": self.min_tvl_usd,
            "stable_only": self.stable_only,
            "max_apy_pct": self.max_apy_pct,
        }


@dataclass(frozen=True)
class AdapterManifest:
    """Validated, immutable manifest for one declarative adapter."""

    name: str
    defillama_protocol_id: str
    chains: Tuple[str, ...]
    symbols: Tuple[str, ...]
    tier: str
    cap: float
    exit_latency_hours: Optional[float]
    exit_latency_profile: str
    quality_gates: QualityGates = field(default_factory=QualityGates)
    pool_ids: Tuple[str, ...] = ()
    source_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "defillama_protocol_id": self.defillama_protocol_id,
            "chains": list(self.chains),
            "symbols": list(self.symbols),
            "tier": self.tier,
            "cap": self.cap,
            "exit_latency": {
                "hours": self.exit_latency_hours,
                "profile": self.exit_latency_profile,
            },
            "quality_gates": self.quality_gates.to_dict(),
            "pool_ids": list(self.pool_ids),
            "source_path": self.source_path,
        }


# ─── Validation helpers (each appends readable problems, never raises) ────────


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _req_str(raw: dict, key: str, problems: List[str]) -> Optional[str]:
    value = raw.get(key)
    if value is None:
        problems.append(f"missing required field '{key}'")
        return None
    if not isinstance(value, str) or not value.strip():
        problems.append(f"field '{key}' must be a non-empty string, got {value!r}")
        return None
    return value.strip()


def _str_list(raw: dict, key: str, default: Tuple[str, ...], problems: List[str]) -> Tuple[str, ...]:
    value = raw.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        problems.append(f"field '{key}' must be a string or a list of strings, got {type(value).__name__}")
        return default
    out: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            problems.append(f"field '{key}' contains a non-string/empty entry: {item!r}")
            continue
        out.append(item.strip())
    if not out:
        problems.append(f"field '{key}' must contain at least one entry")
        return default
    return tuple(out)


def _default_profile(hours: Optional[float]) -> str:
    """Derive the exit-latency bucket name — mirrors classify_exit_latency()."""
    if hours is None:
        return "unknown"
    if hours <= 0.0:
        return "instant"
    if hours <= ILLIQUID_THRESHOLD_HOURS:
        return "liquid"
    return "illiquid"


def validate_manifest(raw: Any, source: str = "<dict>") -> AdapterManifest:
    """Validate a parsed manifest document into an :class:`AdapterManifest`.

    Collects ALL problems and raises a single :class:`ValidationError` (with
    ``.problems``) when any are found. Pure: no I/O, input is not mutated.
    """
    problems: List[str] = []

    if not isinstance(raw, dict):
        raise ValidationError(
            source, [f"manifest must be a mapping/object, got {type(raw).__name__}"]
        )

    name = _req_str(raw, "name", problems)
    slug = _req_str(raw, "defillama_protocol_id", problems)

    chains = _str_list(raw, "chains", ("Ethereum",), problems)
    symbols = _str_list(raw, "symbols", ("USDC",), problems)

    # tier ---------------------------------------------------------------
    tier = raw.get("tier")
    if tier is None:
        problems.append("missing required field 'tier'")
        tier = None
    elif not isinstance(tier, str) or tier.upper() not in VALID_TIERS:
        problems.append(
            f"unknown tier {tier!r} (expected one of {'/'.join(VALID_TIERS)})"
        )
        tier = None
    else:
        tier = tier.upper()

    # cap ------------------------------------------------------------------
    cap = raw.get("cap")
    if cap is None:
        cap_value = DEFAULT_TIER_CAPS.get(tier or "", 0.10)
    elif not _is_num(cap) or not (0.0 < float(cap) <= 1.0):
        problems.append(f"field 'cap' must be a number in (0, 1], got {cap!r}")
        cap_value = DEFAULT_TIER_CAPS.get(tier or "", 0.10)
    else:
        cap_value = float(cap)

    # exit latency -----------------------------------------------------------
    hours: Optional[float] = None
    profile: Optional[str] = None
    exit_raw = raw.get("exit_latency")
    if exit_raw is None and raw.get("exit_latency_hours") is not None:
        exit_raw = {"hours": raw.get("exit_latency_hours")}
    if exit_raw is not None:
        if _is_num(exit_raw):
            exit_raw = {"hours": exit_raw}
        if not isinstance(exit_raw, dict):
            problems.append(
                "field 'exit_latency' must be a mapping {hours, profile} or a number, "
                f"got {type(exit_raw).__name__}"
            )
        else:
            h = exit_raw.get("hours")
            if h is not None:
                if not _is_num(h) or float(h) < 0.0:
                    problems.append(
                        f"field 'exit_latency.hours' must be a number >= 0, got {h!r}"
                    )
                else:
                    hours = float(h)
            p = exit_raw.get("profile")
            if p is not None:
                if not isinstance(p, str) or not p.strip():
                    problems.append("field 'exit_latency.profile' must be a non-empty string")
                else:
                    profile = p.strip()
    if profile is None:
        profile = _default_profile(hours)

    # quality gates ------------------------------------------------------------
    gates_raw = raw.get("quality_gates")
    min_tvl = DEFAULT_MIN_TVL_USD
    stable_only = False
    max_apy: Optional[float] = None
    if gates_raw is not None:
        if not isinstance(gates_raw, dict):
            problems.append(
                f"field 'quality_gates' must be a mapping, got {type(gates_raw).__name__}"
            )
        else:
            g_tvl = gates_raw.get("min_tvl_usd")
            if g_tvl is not None:
                if not _is_num(g_tvl) or float(g_tvl) < 0.0:
                    problems.append(
                        f"field 'quality_gates.min_tvl_usd' must be a number >= 0, got {g_tvl!r}"
                    )
                else:
                    min_tvl = float(g_tvl)
            g_stable = gates_raw.get("stable_only")
            if g_stable is not None:
                if not isinstance(g_stable, bool):
                    problems.append(
                        f"field 'quality_gates.stable_only' must be a boolean, got {g_stable!r}"
                    )
                else:
                    stable_only = g_stable
            g_apy = gates_raw.get("max_apy_pct")
            if g_apy is not None:
                if not _is_num(g_apy) or float(g_apy) <= 0.0:
                    problems.append(
                        f"field 'quality_gates.max_apy_pct' must be a number > 0, got {g_apy!r}"
                    )
                else:
                    max_apy = float(g_apy)

    # explicit pool ids (optional) ------------------------------------------
    pool_ids: Tuple[str, ...] = ()
    if raw.get("pool_ids") is not None:
        ids = raw.get("pool_ids")
        if not isinstance(ids, (list, tuple)) or any(
            not isinstance(i, str) or not i.strip() for i in ids
        ):
            problems.append("field 'pool_ids' must be a list of non-empty strings")
        else:
            pool_ids = tuple(i.strip() for i in ids)

    if problems:
        raise ValidationError(source, problems)

    return AdapterManifest(
        name=name,  # type: ignore[arg-type] - guarded by problems check
        defillama_protocol_id=slug,  # type: ignore[arg-type]
        chains=chains,
        symbols=symbols,
        tier=tier,  # type: ignore[arg-type]
        cap=cap_value,
        exit_latency_hours=hours,
        exit_latency_profile=profile,
        quality_gates=QualityGates(
            min_tvl_usd=min_tvl, stable_only=stable_only, max_apy_pct=max_apy
        ),
        pool_ids=pool_ids,
        source_path=source if source != "<dict>" else None,
    )


# ─── File loading ──────────────────────────────────────────────────────────────


def _parse_text(text: str, suffix: str, source: str) -> Any:
    """Parse manifest text by extension; ValidationError on any parse failure."""
    if suffix == ".json":
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ValidationError(source, [f"invalid JSON: {exc}"]) from None

    # .yaml / .yml
    if yaml is not None:
        try:
            return yaml.safe_load(text)
        except Exception as exc:  # yaml.YAMLError and friends
            raise ValidationError(source, [f"invalid YAML: {exc}"]) from None

    # Graceful fallback without PyYAML: JSON is a YAML subset, so a
    # JSON-compatible .yaml body still loads.
    try:
        return json.loads(text)
    except ValueError:
        raise ValidationError(
            source,
            [
                "PyYAML is not installed and the manifest body is not "
                "JSON-compatible — install PyYAML or provide the same "
                "manifest as a .json file"
            ],
        ) from None


def load_manifest_file(path: str | Path) -> AdapterManifest:
    """Load + validate a single ``.yaml``/``.yml``/``.json`` manifest file.

    Raises :class:`ValidationError` (with a readable ``problems`` list) on a
    missing/unreadable file, an unsupported extension, a parse failure or any
    schema problem — never a raw parser stacktrace.
    """
    p = Path(path)
    source = str(p)
    suffix = p.suffix.lower()
    if suffix not in MANIFEST_SUFFIXES:
        raise ValidationError(
            source, [f"unsupported manifest extension {suffix!r} (expected .yaml/.yml/.json)"]
        )
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(source, [f"cannot read manifest file: {exc}"]) from None

    parsed = _parse_text(text, suffix, source)
    return validate_manifest(parsed, source=source)
