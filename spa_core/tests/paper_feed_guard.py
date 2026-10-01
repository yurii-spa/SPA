"""Paper mechanic feeds are never live under test (ADR-533).

The Balanced PT and Aggressive loop models read Pendle, the Morpho API, DeFiLlama and public RPCs.
Under test their DEFAULT transports are replaced by one that raises a named ``OSError``: the models
then report "inputs unmeasured" (their designed third outcome) instead of reaching the network.
Tests that need data inject fakes through the functions' ``get`` / ``post`` / ``get_json`` arguments.
Loaded by BOTH conftests (tests/ and spa_core/tests/ are siblings), like the other guards.
"""
# LLM_FORBIDDEN


def _refuse(*_a, **_k):
    raise OSError("paper feed not injected under test (spa_core/tests/paper_feed_guard.py)")


def install(monkeypatch) -> None:
    import importlib
    for mod, attr in (("spa_core.paper_trading.pendle_market", "_get"),
                      ("spa_core.paper_trading.morpho_market", "_get_json"),
                      ("spa_core.paper_trading.onchain_read", "_default_post")):
        try:
            monkeypatch.setattr(importlib.import_module(mod), attr, _refuse)
        except Exception:  # noqa: BLE001 — a tree without the module has nothing to guard
            pass
