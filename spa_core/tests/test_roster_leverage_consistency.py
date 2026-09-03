"""Roster leverage: the enforcement descriptor (_TIER_DESCRIPTORS) must agree with the leverage each
class actually trades with (self._cfg.get("leverage"/"yt_leverage", <default>)).

Regression for the 2026-09-03 drift: `leverage_loop` traded at 2x (code default, book name) while
_TIER_DESCRIPTORS claimed 3x — the tier-policy check itself was still SAFE (an inflated descriptor only
makes tier_policy's cap check stricter, never looser), but any report/dashboard reading the descriptor
told the owner and site readers a false number. Owner decision 2026-09-03: 2x is correct (matches code
and the book's realized history); the descriptor was fixed to match.

No network, no risk-path import — pure source introspection + the descriptor dict.
"""
import ast
import inspect

from spa_core.strategy_lab.aggressive_lab import roster


def _leverage_literals_by_class() -> dict:
    """AST-walk roster.py: for each class, collect literal defaults passed to
    self._cfg.get("leverage", X) / self._cfg.get("yt_leverage", X) anywhere in its body."""
    source = inspect.getsource(roster)
    tree = ast.parse(source)
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        literals = set()
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            if not (isinstance(func, ast.Attribute) and func.attr == "get"):
                continue
            if not (isinstance(func.value, ast.Attribute) and func.value.attr == "_cfg"):
                continue
            if len(call.args) != 2:
                continue
            key, default = call.args
            if not (isinstance(key, ast.Constant) and key.value in ("leverage", "yt_leverage")):
                continue
            if isinstance(default, ast.Constant) and isinstance(default.value, (int, float)):
                literals.add(float(default.value))
        if literals:
            found[node.name] = literals
    return found


def _class_id_by_name() -> dict:
    return {cls.__name__: cls.id for cls in roster.ROSTER_CLASSES}


def test_every_class_has_exactly_one_leverage_default():
    literals = _leverage_literals_by_class()
    ids = _class_id_by_name()
    multi = {name: vals for name, vals in literals.items() if name in ids and len(vals) > 1}
    assert not multi, (
        f"class(es) declare more than one leverage default in code — which one is real? {multi}"
    )


def test_descriptor_leverage_matches_code_default_for_every_roster_class():
    literals = _leverage_literals_by_class()
    ids = _class_id_by_name()
    mismatches = []
    for class_name, strategy_id in ids.items():
        code_defaults = literals.get(class_name)
        if not code_defaults:
            continue  # class trades unlevered (no self._cfg.get("leverage"/"yt_leverage", ...) call)
        code_leverage = next(iter(code_defaults))
        descriptor_leverage = roster._TIER_DESCRIPTORS.get(strategy_id, {}).get("leverage")
        if descriptor_leverage != code_leverage:
            mismatches.append((strategy_id, "descriptor", descriptor_leverage, "code", code_leverage))
    assert not mismatches, f"descriptor/code leverage drift: {mismatches}"


def test_leverage_loop_is_2x_everywhere_regression():
    assert roster._TIER_DESCRIPTORS["leverage_loop"]["leverage"] == 2.0
    literals = _leverage_literals_by_class()
    assert literals["LeverageLoop"] == {2.0}
