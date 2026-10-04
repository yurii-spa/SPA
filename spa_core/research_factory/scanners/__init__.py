"""spa_core/research_factory/scanners/__init__.py — Package-B scanner registry (ADR-560).

Exposes ``SCANNERS`` — the tuple of scanner modules Package A's ``run.py`` imports and iterates.
Each module exposes ``scan(data_dir, now, *, rpc_client=None) -> dict`` per the frozen Appendix-I
scanner interface in ``contract.py`` / the ADR; see each module's own docstring for what it reads
and why. No scanner writes a file, calls the network itself (``onchain.py`` is the one allowed
exception, gated behind an injected ``rpc_client``), or raises on malformed/missing input.

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from spa_core.research_factory.scanners import basis, cash_treasury, discovery, trading_research, rwa

#: order matches the ADR's own track listing (WP-S02 … WP-S06).
SCANNERS = (cash_treasury, rwa, basis, discovery, trading_research)

__all__ = ["SCANNERS", "cash_treasury", "rwa", "basis", "discovery", "trading_research"]
