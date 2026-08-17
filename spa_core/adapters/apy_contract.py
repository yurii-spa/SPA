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

DECLARED UNITS — the only alternative to guessing (карточка agent-s76-apy-unit-guess)
--------------------------------------------------------------------------------------
Some consumers cannot use ``get_yield_info()`` and must read a raw number
(``get_apy()``, a feed field, a config literal). For those, the unit is
**DECLARED BY THE SOURCE**, never inferred from the magnitude of the number:
a source declares ``APY_UNIT = "decimal"`` or ``APY_UNIT = "percent"``, and
:func:`apy_decimal_from_declared` / :func:`raw_apy_decimal` convert exactly once
against that declaration. **An undeclared unit is a REFUSAL** (``None``, logged)
— never a default, never a magnitude guess. This is the whole point: ``0.8``
meaning 0.8% and ``0.8`` meaning 80% are indistinguishable as numbers, so the
only honest answer without a declaration is «не знаю» (invariant 2, fail-CLOSED).

:func:`adapters_missing_apy_unit` names the sources that have not declared their
unit yet, so the remaining migration is measurable instead of assumed.

Rules (adapter domain):
  * stdlib only, deterministic, no LLM.
  * fail-closed: out-of-band / non-numeric / undeclared unit → ``None``, logged.
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


# ---------------------------------------------------------------------------
# Declared units (explicit contract at the SOURCE, refusal when undeclared)
# ---------------------------------------------------------------------------
APY_UNIT_DECIMAL: str = "decimal"      # 0.052 == 5.2%
APY_UNIT_PERCENT: str = "percent"      # 5.2   == 5.2%
APY_UNITS: tuple = (APY_UNIT_DECIMAL, APY_UNIT_PERCENT)

#: Attribute name a source sets to declare its unit (class, instance or module).
APY_UNIT_ATTR: str = "APY_UNIT"


def declared_apy_unit(source: Any) -> Optional[str]:
    """Return the unit DECLARED by ``source``, or ``None`` when undeclared.

    A source (adapter class/instance, feed object, module) declares its unit as
    ``APY_UNIT = "decimal"`` / ``APY_UNIT = "percent"``. Anything else — the
    attribute missing, non-string, or an unrecognised string — is treated as
    **undeclared** (``None``, logged): a typo must not silently become a unit.

    Never inspects any APY value: the declaration is the only input.
    """
    if source is None:
        return None
    raw = getattr(source, APY_UNIT_ATTR, None)
    if raw is None:
        return None
    if not isinstance(raw, str):
        logger.warning(
            "apy_contract: %s.%s is %r (not a string) — treated as UNDECLARED",
            getattr(source, "PROTOCOL", type(source).__name__), APY_UNIT_ATTR, raw,
        )
        return None
    unit = raw.strip().lower()
    if unit not in APY_UNITS:
        logger.warning(
            "apy_contract: %s.%s=%r is not one of %s — treated as UNDECLARED "
            "(fail-closed; a typo must not become a unit)",
            getattr(source, "PROTOCOL", type(source).__name__), APY_UNIT_ATTR,
            raw, APY_UNITS,
        )
        return None
    return unit


def apy_decimal_from_declared(
    value: Any,
    unit: Optional[str],
    *,
    protocol: str = "?",
) -> Optional[float]:
    """Convert ``value`` to a validated DECIMAL APY using its DECLARED ``unit``.

    ``unit`` must be :data:`APY_UNIT_DECIMAL` or :data:`APY_UNIT_PERCENT`.
    ``None`` / anything else ⇒ **refusal** (``None``, logged): the unit is not
    inferred from the magnitude of ``value``, because 0.8 as «0.8%» and 0.8 as
    «80%» are the same number (карточка agent-s76-apy-unit-guess — the exact
    heuristic this replaces read a true 0.5% APY as 50%).

    The percent→decimal division happens exactly ONCE here; the result then goes
    through :func:`validate_apy_decimal`, so an out-of-band value still fails
    CLOSED rather than being rescaled a second time.
    """
    if unit not in APY_UNITS:
        logger.warning(
            "apy_contract[%s]: APY %r has NO declared unit (%r) — refused. "
            "Declare %s on the source; the unit is never guessed from the "
            "magnitude of the number.",
            protocol, value, unit, APY_UNIT_ATTR,
        )
        return None
    if not _is_real_number(value):
        logger.warning(
            "apy_contract[%s]: non-numeric APY %r rejected (fail-closed)",
            protocol, value,
        )
        return None
    v = float(value)
    if unit == APY_UNIT_PERCENT:
        v = v / 100.0
    return validate_apy_decimal(v, protocol=protocol)


def raw_apy_decimal(source: Any) -> Optional[float]:
    """Read the unit-ambiguous ``get_apy()`` SAFELY, via the source's declaration.

    For consumers that cannot use the canonical ``get_yield_info().apy``
    accessor. Returns a validated decimal, or ``None`` when the source has not
    declared :data:`APY_UNIT_ATTR`, has no ``get_apy()``, the call fails, or the
    value is out of band. Refusal is the answer to «unit unknown» — there is no
    default unit and no magnitude heuristic.
    """
    if source is None:
        return None
    protocol = str(getattr(source, "PROTOCOL", None) or type(source).__name__)
    unit = declared_apy_unit(source)
    if unit is None:
        logger.debug(
            "apy_contract[%s]: no declared %s — raw get_apy() refused",
            protocol, APY_UNIT_ATTR,
        )
        return None
    get_apy = getattr(source, "get_apy", None)
    if not callable(get_apy):
        return None
    try:
        raw = get_apy()
    except Exception as exc:  # noqa: BLE001 - fail-closed
        logger.debug("apy_contract[%s]: get_apy() failed: %s", protocol, exc)
        return None
    return apy_decimal_from_declared(raw, unit, protocol=protocol)


def adapters_missing_apy_unit(registry: Any = None) -> list:
    """Names of ``ADAPTER_REGISTRY`` entries that have NOT declared their unit.

    Measurement helper for the ongoing migration (the units really are
    inconsistent: percent in newer adapters, decimal in aave/yearn/euler/maple —
    `.claude/rules/adapters.md`). Read-only, no network, no instantiation: only
    the class attribute is inspected. ``registry`` may be injected for tests;
    by default ``spa_core.adapters.ADAPTER_REGISTRY`` is imported lazily so this
    module stays importable from anywhere in the adapter package.
    """
    if registry is None:
        from spa_core.adapters import ADAPTER_REGISTRY  # lazy: avoid import cycle
        registry = ADAPTER_REGISTRY
    missing = []
    for entry in registry:
        name, cls = (entry[0], entry[-1]) if isinstance(entry, tuple) else (
            getattr(entry, "PROTOCOL", type(entry).__name__), entry)
        if declared_apy_unit(cls) is None:
            missing.append(str(name))
    return sorted(missing)


def canonical_apy_pct(adapter: Any) -> Optional[float]:
    """Return an adapter's APY as a PERCENT (decimal × 100), or ``None``.

    Convenience wrapper over :func:`canonical_apy_decimal` for the (many)
    consumers that work in percent units. The decimal→percent conversion
    happens exactly ONCE here, from the validated canonical decimal — there is
    no magnitude guessing and no double-scaling.
    """
    dec = canonical_apy_decimal(adapter)
    return None if dec is None else dec * 100.0
