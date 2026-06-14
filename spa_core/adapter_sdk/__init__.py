"""Adapter SDK v1 (SPA-V417 / MP-204) — declarative YAML/JSON protocol adapters.

A NEW, strictly additive package next to ``spa_core/adapters/`` (the existing
file-per-protocol adapters are untouched). It provides:

* :mod:`contract` — the formal ``ProtocolAdapter`` contract
  (``fetch_pools() / exit_latency() / health()``) and the :class:`PoolInfo`
  normalized pool snapshot;
* :mod:`manifest` — YAML (or JSON fallback) manifest schema + validation;
* :mod:`declarative_adapter` — :class:`DeclarativeAdapter`, implementing the
  contract from a manifest on top of the existing DeFiLlama feed;
* :mod:`registry` — manifest discovery, ``load_all()`` and a thin CLI.

STRICTLY READ-ONLY (SPA-BL-011): this package only reads public yield data and
writes one derived advisory report. It never moves capital and is NOT imported
by ``execution/``, ``risk/``, ``allocator/`` or the feed-health domain.
"""
from .contract import PoolInfo, ProtocolAdapter, VALID_TIERS, DEFAULT_TIER_CAPS
from .manifest import AdapterManifest, QualityGates, ValidationError, load_manifest_file, validate_manifest
from .declarative_adapter import DeclarativeAdapter

# NOTE: ``registry`` is deliberately NOT imported here so that
# ``python3 -m spa_core.adapter_sdk.registry`` runs without the runpy
# "found in sys.modules" RuntimeWarning. Use
# ``from spa_core.adapter_sdk.registry import load_all``.

__all__ = [
    "PoolInfo",
    "ProtocolAdapter",
    "VALID_TIERS",
    "DEFAULT_TIER_CAPS",
    "AdapterManifest",
    "QualityGates",
    "ValidationError",
    "load_manifest_file",
    "validate_manifest",
    "DeclarativeAdapter",
]
