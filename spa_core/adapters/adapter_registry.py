"""
Central adapter registry — all adapters auto-register here.

MP-389: ADAPTER_REGISTRY — центральный реестр адаптеров.

Two registration mechanisms are supported:

1. **Metaclass auto-registration** — new adapters that inherit from
   ``RegistryBaseAdapter`` are registered automatically; the ``PROTOCOL``
   class attribute becomes the registry key.

2. **Explicit registration** — existing adapters (CompoundV3Adapter,
   AaveV3Adapter, …) can be registered without changing their class hierarchy::

       from spa_core.adapters.adapter_registry import REGISTRY
       REGISTRY["compound_v3"] = CompoundV3Adapter

   This is the *preferred path* for existing code to avoid breaking tests.

``cycle_runner`` calls ``refresh_all()`` which iterates over all registered
adapters, extracts the current APY, and updates ``data/adapter_status.json``
atomically (tmp + os.replace).

Constraints:
- Stdlib only — no third-party imports.
- Atomic writes everywhere.
- LLM FORBIDDEN (risk/execution/monitoring domain).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional, Type

from spa_core.utils.errors import AdapterError, safe_call

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Central registry  {protocol_key: adapter_class}
# ---------------------------------------------------------------------------

REGISTRY: Dict[str, Type] = {}

# ---------------------------------------------------------------------------
# Metaclass — auto-registers any subclass that declares PROTOCOL
# ---------------------------------------------------------------------------


class RegistryMeta(type):
    """Metaclass that auto-registers concrete adapters into REGISTRY.

    A class is registered when:
    * It has a non-empty ``PROTOCOL`` class attribute.
    * It is not the ``RegistryBaseAdapter`` base class itself (``bases`` check).

    Example::

        class MyAdapter(RegistryBaseAdapter):
            PROTOCOL = "my_protocol"
            TIER = "T2"
            DEFAULT_APY_PCT = 5.0

            def get_apy_pct(self) -> float:
                return 5.0  # live fetch in production
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple,
        namespace: dict,
    ) -> "RegistryMeta":
        cls = super().__new__(mcs, name, bases, namespace)
        protocol: str = namespace.get("PROTOCOL", "")
        # Register only concrete subclasses (not the base class itself)
        if protocol and bases:
            REGISTRY[protocol] = cls
        return cls


# ---------------------------------------------------------------------------
# RegistryBaseAdapter — new base class for MP-389 adapters
# Note: deliberately NOT inheriting from spa_core.adapters.base_adapter.BaseAdapter
# to avoid breaking existing adapter tests that check isinstance / ABC.
# ---------------------------------------------------------------------------


class RegistryBaseAdapter(metaclass=RegistryMeta):
    """Lightweight base class for adapters that want auto-registration.

    Existing adapters (AaveV3Adapter, CompoundV3Adapter, …) do NOT need to
    inherit from this class — use explicit REGISTRY["key"] = Class instead.
    """

    PROTOCOL: str = ""
    TIER: str = "T1"
    DEFAULT_APY_PCT: float = 0.0

    def get_apy_pct(self) -> float:
        """Return the current APY in percent (e.g. 4.8 for 4.8%).

        Override in concrete subclasses to perform a live fetch.
        Falls back to DEFAULT_APY_PCT.
        """
        return self.DEFAULT_APY_PCT

    def health_check(self) -> str:
        """Return "ok" or "degraded" / "error"."""
        return "ok"

    def to_dict(self) -> dict:
        """Return a summary dict (used for logging / dashboards)."""
        return {
            "protocol": self.PROTOCOL,
            "tier": self.TIER,
            "apy_pct": self.get_apy_pct(),
        }


# ---------------------------------------------------------------------------
# Helper — extract APY percent from any adapter instance
# ---------------------------------------------------------------------------


def _extract_apy_pct(adapter_instance: Any) -> Optional[float]:
    """Try various adapter interfaces to retrieve an APY percentage.

    Priority order:
    1. ``get_apy_pct()`` — MP-389 RegistryBaseAdapter interface.
    2. ``get_yield_info().apy`` — BaseAdapter ABC (decimal → ×100).
    3. ``get_apy()`` — BaseAdapter ABC shortcut (decimal → ×100).
    4. ``fetch()["apy"]`` — standalone adapters (CompoundV3Adapter pattern).

    Returns None on any failure so the caller can decide what to do.
    """
    # 1. New MP-389 interface
    if hasattr(adapter_instance, "get_apy_pct") and callable(
        adapter_instance.get_apy_pct
    ):
        try:
            val = adapter_instance.get_apy_pct()
            if val is not None:
                return float(val)
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_apy_pct() failed: %s", exc)

    # 2. BaseAdapter abstract interface: get_yield_info().apy  (decimal)
    if hasattr(adapter_instance, "get_yield_info") and callable(
        adapter_instance.get_yield_info
    ):
        try:
            info = adapter_instance.get_yield_info()
            if info is not None and getattr(info, "apy", None) is not None:
                return float(info.apy) * 100.0
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_yield_info() failed: %s", exc)

    # 3. BaseAdapter shortcut: get_apy() (decimal)
    if hasattr(adapter_instance, "get_apy") and callable(adapter_instance.get_apy):
        try:
            val = adapter_instance.get_apy()
            if val is not None:
                return float(val) * 100.0
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_apy() failed: %s", exc)

    # 4. Standalone adapter pattern: fetch()["apy"]  (percent)
    if hasattr(adapter_instance, "fetch") and callable(adapter_instance.fetch):
        try:
            result = adapter_instance.fetch()
            if isinstance(result, dict) and result.get("apy") is not None:
                return float(result["apy"])
        except Exception as exc:  # noqa: BLE001
            logger.debug("fetch()['apy'] failed: %s", exc)

    return None


def _extract_tier(adapter_class: Type) -> str:
    """Best-effort extraction of tier from an adapter class."""
    for attr in ("TIER", "tier", "ORCHESTRATOR_TIER"):
        val = getattr(adapter_class, attr, None)
        if val and isinstance(val, str) and val.startswith("T"):
            return val
    return "T2"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_all_adapters() -> List[Any]:
    """Instantiate every registered adapter and return the list.

    Adapters that fail to instantiate are skipped (logged as warnings).
    """
    instances: List[Any] = []
    for protocol, cls in list(REGISTRY.items()):
        try:
            instances.append(cls())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "AdapterRegistry: could not instantiate %s (%s): %s",
                protocol,
                cls.__name__,
                exc,
            )
    return instances


def refresh_all(
    adapter_status_path: str = "data/adapter_status.json",
) -> Dict[str, Any]:
    """Refresh APY for every registered adapter and persist to adapter_status.json.

    Reads the existing file, merges in fresh APY values keyed by protocol,
    and writes back atomically (tmp + os.replace).

    Returns a dict ``{protocol: apy_pct}`` for live adapters, or
    ``{protocol: {"error": "..."}}`` when an adapter fails.
    """
    # ── Load existing status (tolerate missing / corrupt file) ──────────────
    try:
        with open(adapter_status_path, encoding="utf-8") as fh:
            status: dict = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        status = {}

    results: Dict[str, Any] = {}

    for protocol, cls in list(REGISTRY.items()):
        try:
            instance = cls()
            apy = _extract_apy_pct(instance)
            if apy is None:
                raise AdapterError(protocol, "no APY available from any interface")
            results[protocol] = apy
            tier = _extract_tier(cls)
            ts = int(time.time())
            if protocol in status and isinstance(status[protocol], dict):
                status[protocol]["apy"] = apy
                status[protocol]["last_refreshed"] = ts
            else:
                status[protocol] = {
                    "apy": apy,
                    "tier": tier,
                    "last_refreshed": ts,
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "AdapterRegistry.refresh_all: adapter %s failed: %s",
                protocol,
                exc,
            )
            results[protocol] = {"error": str(exc)}

    # ── Atomic write ─────────────────────────────────────────────────────────
    dir_ = os.path.dirname(os.path.abspath(adapter_status_path))
    os.makedirs(dir_, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_, prefix=".tmp_adapter_status_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(status, fh, indent=2)
        os.replace(tmp_path, adapter_status_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return results


def register(protocol_key: str, adapter_class: Type) -> None:
    """Explicitly register an adapter class under ``protocol_key``.

    Use this for existing adapters that do not inherit RegistryBaseAdapter::

        from spa_core.adapters.adapter_registry import register
        from spa_core.adapters.aave_v3 import AaveV3Adapter
        register("aave_v3", AaveV3Adapter)
    """
    REGISTRY[protocol_key] = adapter_class


def unregister(protocol_key: str) -> bool:
    """Remove an adapter from the registry (useful in tests).

    Returns True if the key existed, False otherwise.
    """
    return REGISTRY.pop(protocol_key, None) is not None
