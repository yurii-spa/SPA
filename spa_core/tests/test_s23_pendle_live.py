# LLM_FORBIDDEN
"""S23 → live MP-201 Pendle feed (ADR-059). Hermetic: patches the feed fn, no live network."""
# LLM_FORBIDDEN

from __future__ import annotations

from spa_core.strategies.s23_pendle_pt_fixed import PendlePTFixedStrategy, MOCK_PT_APY


def _mk():
    return PendlePTFixedStrategy()


def test_live_pendle_reading_is_used_and_flagged_live():
    s = _mk()
    s._pendle_apy_fn = lambda fb=MOCK_PT_APY: {"apy": 9.2, "source": "pendle_api", "is_available": True}
    assert s.get_pt_apy() == 9.2
    assert s._pt_live is True


def test_fallback_source_is_not_dressed_up_as_live():
    # API down → get_pendle_apy returns a fallback dict → S23 must use its OWN mock, flagged NOT live.
    s = _mk()
    s._pendle_apy_fn = lambda fb=MOCK_PT_APY: {"apy": fb, "source": "fallback", "is_available": True}
    assert s.get_pt_apy() == MOCK_PT_APY
    assert s._pt_live is False


def test_unavailable_market_is_mock():
    s = _mk()
    s._pendle_apy_fn = lambda fb=MOCK_PT_APY: {"apy": 0.0, "source": "pendle_api", "is_available": False}
    assert s.get_pt_apy() == MOCK_PT_APY
    assert s._pt_live is False


def test_missing_feed_fn_falls_back_to_mock_not_crash():
    # the OLD bug: a dead adapter import → S23 silently on mock. Now: no fn → honest mock, no crash.
    s = _mk()
    s._pendle_apy_fn = None
    assert s.get_pt_apy() == MOCK_PT_APY
    assert s._pt_live is False


def test_feed_fn_raising_does_not_crash_strategy():
    def _boom(fb=MOCK_PT_APY):
        raise RuntimeError("network exploded")
    s = _mk()
    s._pendle_apy_fn = _boom
    assert s.get_pt_apy() == MOCK_PT_APY
    assert s._pt_live is False


def test_does_not_import_the_retired_adapter():
    # guard: S23 must NOT import the retired MP-354 pendle_pt_adapter (raises ImportError).
    import ast
    from pathlib import Path
    src = Path(PendlePTFixedStrategy.__module__.replace(".", "/") + ".py")
    # resolve within the repo
    import spa_core.strategies.s23_pendle_pt_fixed as mod
    text = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert "spa_core.adapters.pendle_pt_adapter" not in imports, "must not import the retired MP-354 module"
    assert "spa_core.adapters.pendle_pt" in imports, "must import the live MP-201 feed"
