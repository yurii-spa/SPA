"""A network-free stand-in for the adapter registry, for tests that only need
the universe to HAVE registry rows — not to fetch them.

Why this exists (2026-08-19, card ``agent-tests-reach-live-feed-222``)
----------------------------------------------------------------------
``spa_core.dfb.pool_universe.build_universe`` assembles the followed-pool
universe from THREE sources, and two of them are injectable already::

    surface=...        # rates-desk quotes      → injected by every dfb test
    breadth_rows=...   # keyless DeFiLlama rows → injected by every dfb test
    ADAPTER_REGISTRY   # ~35 adapters           → NOT injectable, read live

The third one is the hole. ``_pool_from_adapter`` constructs each registry
adapter and calls ``get_yield_info()``; roughly a dozen adapters carry their
OWN feed URL and their OWN ``urlopen`` (``yields.llama.fi``,
``api.fluid.instadapp.io``, ``api-v2.pendle.finance``, ``ethena.fi``,
``usual.money``), so the shared doors in ``live_feed_doors.py`` do not cover
them. Measured in this container on 2026-08-19, one ``build_universe()`` call
costs **21 refused live-feed attempts**, and the six-file ``dfb`` slice costs
462 from 21 tests.

The cost is not bandwidth — ``network_guard`` refuses every one and nothing
goes out. The cost is that the refusal is INDISTINGUISHABLE from the answer:
``_pool_from_adapter`` catches the failure and returns a row whose ``apy_total``
and ``tvl_usd`` are ``None``. So ``test_universe_no_fabricated_cells``, whose
body is ``if p.apy_total is not None: assert ...``, asserts NOTHING about any
registry pool — the branch it means to check is never entered. It is green
because the feed is down, and it stays green when the code it guards breaks.

What this module changes — and what it deliberately does not
------------------------------------------------------------
It replaces the SOURCE of adapters, not the code that reads them. Every line of
``_pool_from_adapter`` still runs for real: construction, ``get_yield_info()``,
``_norm_apy_decimal`` clamping, the ``pool_id`` build, the de-dup by deepest
TVL, the ``as_of`` stamping. Only the transport disappears — the same trade the
rest of this suite already makes with ``FakeFeed`` (``.claude/rules/adapters.md``:
"тесты инжектят FakeFeed … не завязывать тесты на живую сеть").

Three fakes, because the real registry exercises three shapes and dropping any
one of them WOULD be a weakening (invariant #16):

============================  =================================================
fake                          the path it keeps covered
============================  =================================================
``_HealthyT1``                a live row: real APY/TVL cells, so the
                              "no fabricated cells" assertions actually run
                              instead of skipping over ``None``
``_HealthyT2``                a second row + a different tier, so the sort /
                              uniqueness / de-dup assertions have something to
                              order
``_FeedDownT3``               ``get_yield_info()`` raises → the fail-CLOSED
                              hole (``None`` cells, row KEPT not dropped). This
                              is the path the live registry takes today for all
                              35 adapters; keeping one fake on it is why this
                              swap adds coverage instead of trading it away.
============================  =================================================

Naming: the list is ``FAKE_ADAPTERS``, never ``ADAPTER_REGISTRY``. One name, one
object (``test_adapter_registry_single_name.py``) — a second definition of that
name is exactly the defect cycle #274 spent a day undoing.
"""
from __future__ import annotations

import contextlib
from typing import Iterator, List, Tuple

from spa_core.adapters.base_adapter import YieldInfo


class _FakeAdapterBase:
    """Minimal read-only adapter surface: what ``_pool_from_adapter`` touches."""

    PROTOCOL = "fake"
    asset = "USDC"

    def get_yield_info(self) -> YieldInfo:  # pragma: no cover - overridden
        raise NotImplementedError


class _HealthyT1(_FakeAdapterBase):
    """A live-feed row with real cells (decimal APY, live TVL provenance)."""

    PROTOCOL = "fake_t1"
    asset = "USDC"

    def get_yield_info(self) -> YieldInfo:
        return YieldInfo(
            protocol="fake_t1", asset="USDC", apy=0.0525, tvl_usd=250_000_000.0,
            tier="T1", risk_score=0.15, exit_latency_hours=0.0, tvl_source="live",
        )


class _HealthyT2(_FakeAdapterBase):
    """A second live row, different tier/asset, for ordering + de-dup coverage."""

    PROTOCOL = "fake_t2"
    asset = "USDT"

    def get_yield_info(self) -> YieldInfo:
        return YieldInfo(
            protocol="fake_t2", asset="USDT", apy=0.0910, tvl_usd=42_000_000.0,
            tier="T2", risk_score=0.45, exit_latency_hours=0.0, tvl_source="live",
        )


class _FeedDownT3(_FakeAdapterBase):
    """The fail-CLOSED path: the feed is unavailable, so the row has holes.

    This is what EVERY registry adapter does today when the network is refused.
    Injected on purpose so swapping the registry cannot quietly drop the
    ``None``-cell branch from the tests that use it.
    """

    PROTOCOL = "fake_down"
    asset = "USDC"

    def get_yield_info(self) -> YieldInfo:
        raise RuntimeError("live feed unavailable (fake, no network)")


#: (key, tier, adapter_cls) — the exact shape of the entries build_universe reads.
FAKE_ADAPTERS: List[Tuple[str, str, type]] = [
    ("fake_t1", "T1", _HealthyT1),
    ("fake_t2", "T2", _HealthyT2),
    ("fake_down", "T3", _FeedDownT3),
]


@contextlib.contextmanager
def injected(entries=None) -> Iterator[List[Tuple[str, str, type]]]:
    """Swap ``spa_core.adapters.ADAPTER_REGISTRY`` for the fakes, then put the
    real one back — even if the test body raises.

    Patched on the MODULE because ``pool_universe.build_universe`` imports the
    name lazily inside the function body (``from spa_core.adapters import
    ADAPTER_REGISTRY``), so the lookup happens per call and the swap is seen by
    every indirect caller too (``risk_overlay.build_and_write``,
    ``riskwire.subjects``, ``dfb.portfolio``) without threading a parameter
    through four modules.
    """
    import spa_core.adapters as _adapters

    use = FAKE_ADAPTERS if entries is None else list(entries)
    original = _adapters.ADAPTER_REGISTRY
    _adapters.ADAPTER_REGISTRY = use
    try:
        yield use
    finally:
        _adapters.ADAPTER_REGISTRY = original
