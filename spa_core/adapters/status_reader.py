"""Shared reader for ``data/adapter_status.json`` (ADR-063 / D1).

ONE place that knows the file's schema, so an adapter can never again read the
wrong shape and silently report a hardcoded constant as a live yield.

The defect this replaces (measured 2026-08-02): the file moved its per-protocol
payload under ``adapters``, but twelve adapters still looked for their block at
the TOP level. Every one of them therefore found nothing on every call. Nine
answered with their hardcoded ``DEFAULT_APY_PCT`` — which the WS1.1 provider then
stamped ``apy_source="live"``, so a literal from 2026-06 ranked money-path capital
as if it were an observation (e.g. ``spark_susds`` ranked at 5.5 % while its
observed 3.3192 % sat unread in the same file). The other three answered ``None``
honestly but were equally blind: their live values were in the file too.

Contract — what counts as an observation:

* ``adapters[<protocol>].live_apy`` — the producer's explicit "I observed this".
  ``null`` means it did NOT, and then the sibling ``apy`` field merely echoes
  ``fallback_apy``. So ``apy`` is NEVER read from this section: it cannot
  distinguish a reading from a literal.
* Legacy top-level blocks (``morpho_steakhouse``, ``aave_arbitrum``, ``pendle_pt``)
  predate the ``adapters`` section and carry no ``live_apy`` field; there the
  block's own ``apy`` IS the producer's reading. Only consulted when the modern
  section is absent for that protocol.

No fake fallback (``.claude/rules/adapters.md``): no data ⇒ ``None``. Callers must
treat ``None`` as "no live data", never as 0 %.

Pure stdlib. Never raises.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
STATUS_FILENAME = "adapter_status.json"

# Upper sanity bound for a live APY in PERCENT. Above this the feed is malformed,
# not generous (mirrors DeFiLlama's APY_SANITY_MAX) → treated as no reading.
#
# There is deliberately NO lower bound. An observed 0 % or negative APY is DATA:
# a pool really can pay nothing, or cost more than it earns. Rejecting it here
# would collapse "we observed zero" into "we observed nothing" — the exact
# conflation this module exists to end, and it would silently drop a genuine
# warning signal. Whether such a pool may receive capital is a POLICY question,
# decided downstream (the allocator's own live band already excludes apy ≤ 0).
# Existing compound_v3 tests pin this: an observed -1 % / 0 % must survive.
_MAX_APY_PCT = 200.0


def _valid_pct(value: object) -> Optional[float]:
    """Return ``value`` as a percent float when it is a usable live reading."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    f = float(value)
    if not math.isfinite(f):
        return None
    if f > _MAX_APY_PCT:
        return None
    return f


def read_status_doc(data_dir: Optional[Path] = None) -> dict:
    """Load ``adapter_status.json``. Returns ``{}`` on any error. Never raises."""
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    try:
        with open(ddir / STATUS_FILENAME, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else {}
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        logger.debug("status_reader: %s unreadable (%s)", STATUS_FILENAME, exc)
        return {}


def read_status_block(protocol: str, data_dir: Optional[Path] = None) -> dict:
    """Return the per-protocol block, modern schema first, then legacy keys."""
    doc = read_status_doc(data_dir)
    adapters = doc.get("adapters")
    if isinstance(adapters, dict):
        block = adapters.get(protocol)
        if isinstance(block, dict):
            return block
    for legacy_key in (protocol, "{}_adapter".format(protocol)):
        block = doc.get(legacy_key)
        if isinstance(block, dict):
            return block
    return {}


def read_live_apy_pct(protocol: str, data_dir: Optional[Path] = None) -> Optional[float]:
    """Observed APY in PERCENT for ``protocol``, or ``None`` when not observed.

    ``None`` is returned for: file missing/unreadable, protocol absent,
    ``live_apy: null`` (the producer could not observe it), or a value outside
    the sanity band. A hardcoded literal is never returned in place of a reading.
    """
    doc = read_status_doc(data_dir)
    adapters = doc.get("adapters")
    if isinstance(adapters, dict):
        block = adapters.get(protocol)
        if isinstance(block, dict):
            # Modern schema: live_apy is the ONLY field that proves observation.
            return _valid_pct(block.get("live_apy"))

    # Legacy top-level block: no live_apy field exists there; the block is written
    # by a live producer, so its own ``apy`` is the reading.
    for legacy_key in (protocol, "{}_adapter".format(protocol)):
        block = doc.get(legacy_key)
        if isinstance(block, dict):
            return _valid_pct(block.get("apy"))

    return None
