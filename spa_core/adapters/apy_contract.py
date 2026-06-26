"""Canonical APY-unit contract for SPA adapters (Architect P3-5).

Background — the latent 100x hazard
-----------------------------------
SPA adapters historically disagreed on the units returned by ``get_apy()``:

  * **decimal** adapters (aave_v3, yearn_v3, euler_v2, btc_lending, …)
    return ``0.052`` to mean 5.2%.
  * **percent** adapters (susde, spark_susds, several Base/L2 feeds)
    return ``5.2`` to mean 5.2%.

``get_apy()`` is therefore **NOT** a safe cross-adapter accessor — its units
depend on the concrete adapter. Production has been safe ONLY because the live
consumers read :meth:`BaseAdapter.get_yield_info`'s ``.apy`` field, which every
adapter normalises to a **decimal**. The danger was in the two code paths that
bypassed that accessor and operated on the raw ``get_apy()`` magnitude:

  (a) ``adapter_registry._extract_apy_pct`` step-3 did ``get_apy() * 100``
      unit-blind — a future percent-adapter without ``get_apy_pct()`` would be
      100x-deflated.
  (b) a ``v < 1.0 → ×100`` heuristic copy-pasted across S22–S40 silently
      mishandles a TRUE sub-1% APY (e.g. btc_lending's honest ~0.5% read by a
      percent path would become 50%).

THE CONTRACT (this module makes it explicit + enforced)
-------------------------------------------------------
``adapter.get_yield_info().apy`` is THE canonical APY accessor. It is a
**DECIMAL** fraction (``0.05`` == 5%) or ``None`` when there is no live data.
Anything that needs a percent must convert exactly once via this accessor.

Use :func:`canonical_apy_decimal` / :func:`canonical_apy_pct` instead of calling
``get_apy()`` directly. They route through ``get_yield_info().apy`` and validate
the value sits in a sane decimal band — a misconfigured adapter is caught and
fails CLOSED (returns ``None`` / logs), never silently 100x-scaled.

Rules (adapter domain):
  * stdlib only, deterministic, no LLM.
  * fail-closed: out-of-band / non-numeric → ``None``, logged.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical sane band for a DECIMAL APY.
#   0.0   == 0%   (legitimate — e.g. btc_lending honest near-zero supply yield)
#   1.0   == 100% (soft cap — anything above is treated as a unit error, almost
#                  certainly a percent value leaking into the decimal accessor)
# A value just below the cap is implausible-but-not-impossible; we LOG it but
# still accept it (warn band). A value strictly above the cap fails CLOSED.
# ---------------------------------------------------------------------------
APY_DECIMAL_MIN: float = 0.0
APY_DECIMAL_SOFT_CAP: float = 1.0          # 100% — hard reject above this
APY_DECIMAL_WARN_ABOVE: float = 0.50       # 50% — accept but log (suspicious)


def _is_real_number(value: Any) -> bool:
    """True only for a finite, non-bool int/float."""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    v = float(value)
    # NaN / inf guard
    return v == v and v not in (float("inf"), float("-inf"))


def validate_apy_decimal(
    apy: Any,
    *,
    protocol: str = "?",
    soft_cap: float = APY_DECIMAL_SOFT_CAP,
) -> Optional[float]:
    """Validate that ``apy`` is a sane DECIMAL APY; fail CLOSED otherwise.

    Returns the value as ``float`` when it is a finite number in
    ``[APY_DECIMAL_MIN, soft_cap]``. Returns ``None`` (and logs) for:

      * ``None`` / non-numeric / NaN / inf,
      * negative values,
      * values strictly above ``soft_cap`` (100% by default) — this is the
        signal of a percent value leaking into the decimal accessor (the 100x
        hazard) and is rejected rather than silently mis-scaled.

    A value in ``(APY_DECIMAL_WARN_ABOVE, soft_cap]`` is accepted but logged as
    suspicious, so a misconfigured-but-plausible adapter still surfaces.

    This is the single enforcement point for the canonical contract; it never
    rescales — it only accepts or rejects.
    """
    if apy is None:
        return None
    if not _is_real_number(apy):
        logger.warning(
            "apy_contract[%s]: non-numeric APY %r rejected (fail-closed)",
            protocol, apy,
        )
        return None
    v = float(apy)
    if v < APY_DECIMAL_MIN:
        logger.warning(
            "apy_contract[%s]: negative APY %.6f rejected (fail-closed)",
            protocol, v,
        )
        return None
    if v > soft_cap:
        logger.warning(
            "apy_contract[%s]: APY %.6f exceeds decimal soft-cap %.2f "
            "(== %.0f%%). Looks like a PERCENT value in the DECIMAL accessor "
            "(100x unit hazard) — rejected, fail-closed.",
            protocol, v, soft_cap, soft_cap * 100.0,
        )
        return None
    if v > APY_DECIMAL_WARN_ABOVE:
        logger.warning(
            "apy_contract[%s]: APY %.6f (== %.1f%%) is implausibly high but "
            "within soft-cap — accepted, verify adapter units.",
            protocol, v, v * 100.0,
        )
    return v


def canonical_apy_decimal(adapter: Any) -> Optional[float]:
    """Return an adapter's APY as a validated DECIMAL via the canonical accessor.

    Reads ``adapter.get_yield_info().apy`` (the canonical accessor — NOT the
    unit-ambiguous ``get_apy()``) and runs it through :func:`validate_apy_decimal`.
    Returns ``None`` on any failure (no live data, non-conforming adapter,
    out-of-band value) — fail-closed, never raises.
    """
    if adapter is None:
        return None
    protocol = getattr(adapter, "PROTOCOL", None) or type(adapter).__name__
    get_info = getattr(adapter, "get_yield_info", None)
    if not callable(get_info):
        logger.debug(
            "apy_contract[%s]: adapter has no get_yield_info() — cannot use "
            "canonical accessor", protocol,
        )
        return None
    try:
        info = get_info()
    except Exception as exc:  # noqa: BLE001 - fail-closed
        logger.debug("apy_contract[%s]: get_yield_info() failed: %s", protocol, exc)
        return None
    if info is None:
        return None
    return validate_apy_decimal(getattr(info, "apy", None), protocol=str(protocol))


def canonical_apy_pct(adapter: Any) -> Optional[float]:
    """Return an adapter's APY as a PERCENT (decimal × 100), or ``None``.

    Convenience wrapper over :func:`canonical_apy_decimal` for the (many)
    consumers that work in percent units. The decimal→percent conversion
    happens exactly ONCE here, from the validated canonical decimal — there is
    no magnitude guessing and no double-scaling.
    """
    dec = canonical_apy_decimal(adapter)
    return None if dec is None else dec * 100.0
