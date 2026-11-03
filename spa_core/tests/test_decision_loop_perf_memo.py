"""perf/decision-loop (замер 03.11): память вердиктов двери книги и ответов сравнения.

Мост находок (`com.spa.decision_loop`) не укладывался в окно гейта: прибор цены
починки адаптеров зовёт судью (`evaluate_window`) по разу на день журнала, и каждый
проход судьи заново спрашивает `RiskPolicy.check_portfolio_health` о тех же книгах
(1 080 786 вызовов за 330 с при 726 разных записях). Правка — память на время
ОДНОЙ переписи / одного процесса моста. Здесь — что она ничего не меняет в ответе:

* вне `book_verdict_memo()` памяти нет вовсе (дневной цикл и тесты — как прежде);
* внутри — повтор не зовёт политику, ответ и сводка гипотетических проверок те же;
* подмена политики МЕЖДУ двумя областями видна (память снимается на выходе);
* ответ сравнения отдаётся КОПИЕЙ — правка его вызывающим не портит память;
* обход сайтов записи в `cio_target_producers` даёт тот же ответ, что прежний.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest import mock

from spa_core.paper_trading import trim_admissibility as ta
from spa_core.risk.policy import RiskPolicy

_BOOK = {"aave_v3": 40_000.0, "euler_v2": 40_000.0}
_APY = {"aave_v3": 4.0, "euler_v2": 0.7}
_TIERS = {"aave_v3": "T1", "euler_v2": "T1"}
_CHAINS = {"aave_v3": "ethereum", "euler_v2": "ethereum"}
_REPO = Path(__file__).resolve().parents[2]


def _ask():
    return ta.book_verdict(_BOOK, _APY, 100_000.0, tiers=_TIERS, chains=_CHAINS)


class _CountPolicy:
    def __init__(self):
        self.calls = 0
        self.orig = RiskPolicy.check_portfolio_health

    def __enter__(self):
        outer = self

        def counted(policy, *a, **k):
            outer.calls += 1
            return outer.orig(policy, *a, **k)

        self.patch = mock.patch.object(RiskPolicy, "check_portfolio_health", counted)
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()


class BookVerdictMemo(unittest.TestCase):
    def setUp(self):
        ta.reset_hypothetical_check_summary()

    def test_without_scope_every_call_asks_the_policy(self):
        with _CountPolicy() as c:
            a, b = _ask(), _ask()
        self.assertEqual(c.calls, 2)
        self.assertEqual(a, b)
        self.assertIsNone(ta._VERDICT_MEMO)

    def test_inside_scope_a_repeat_does_not_ask_and_answers_the_same(self):
        with _CountPolicy() as c:
            plain = _ask()
            plain_summary = ta.hypothetical_check_summary()
            ta.reset_hypothetical_check_summary()
            with ta.book_verdict_memo():
                first, second, third = _ask(), _ask(), _ask()
        self.assertEqual(c.calls, 2)                      # 1 без памяти + 1 в области
        self.assertEqual(first, plain)
        self.assertEqual(second, plain)
        self.assertEqual(third, plain)
        self.assertFalse(first[0]["approved"])            # книга с отказом — предмет не пустой
        # сводка ведётся и на повторе: три проверки, те же классы
        summary = ta.hypothetical_check_summary()
        self.assertEqual(summary["checked"], 3)
        for kind in ("violations", "warnings"):
            self.assertEqual(
                {k: v["count"] // 3 for k, v in summary[kind]["classes"].items()},
                {k: v["count"] for k, v in plain_summary[kind]["classes"].items()})

    def test_a_policy_swapped_between_two_scopes_is_seen(self):
        with ta.book_verdict_memo():
            before = _ask()[0]["approved"]
        approve_all = lambda policy, state, **k: type(  # noqa: E731
            "R", (), {"approved": True, "violations": [], "warnings": [],
                      "required_response": "NONE"})()
        with mock.patch.object(RiskPolicy, "check_portfolio_health", approve_all):
            with ta.book_verdict_memo():
                after = _ask()[0]["approved"]
        self.assertFalse(before)
        self.assertTrue(after)                            # память не пережила область

    def test_nested_scope_shares_one_memory_and_the_outer_exit_clears_it(self):
        with ta.book_verdict_memo():
            outer = ta._VERDICT_MEMO
            with ta.book_verdict_memo():
                self.assertIs(ta._VERDICT_MEMO, outer)
            self.assertIs(ta._VERDICT_MEMO, outer)
        self.assertIsNone(ta._VERDICT_MEMO)
        self.assertIsNone(ta._COMPARE_MEMO)

    def test_unknown_tier_is_the_third_outcome_with_or_without_memory(self):
        tiers = {"aave_v3": "T1"}
        plain = ta.book_verdict(_BOOK, _APY, 100_000.0, tiers=tiers, chains=_CHAINS)
        with ta.book_verdict_memo():
            remembered = ta.book_verdict(_BOOK, _APY, 100_000.0, tiers=tiers, chains=_CHAINS)
        self.assertEqual(plain, (None, ["euler_v2"]))
        self.assertEqual(remembered, plain)


class ComparisonMemo(unittest.TestCase):
    def test_answer_is_a_copy_and_a_repeat_is_not_recomputed(self):
        calls = []

        @ta.remember_comparison
        def compare(current, *, params):
            calls.append(1)
            return {"rows": [dict(current)], "params": params}

        with ta.book_verdict_memo():
            first = compare({"a": 1.0}, params=("p", 1))
            first["rows"][0]["a"] = 999.0                 # вызывающий правит ответ
            second = compare({"a": 1.0}, params=("p", 1))
            other = compare({"a": 2.0}, params=("p", 1))
        self.assertEqual(len(calls), 2)                   # повтор не пересчитан, другой вход — да
        self.assertEqual(second["rows"][0]["a"], 1.0)     # память не испорчена правкой
        self.assertEqual(other["rows"][0]["a"], 2.0)
        compare({"a": 1.0}, params=("p", 1))
        self.assertEqual(len(calls), 3)                   # вне области — всегда пересчёт

    def test_input_that_does_not_serialise_is_never_remembered(self):
        calls = []

        @ta.remember_comparison
        def compare(book):
            calls.append(1)
            return len(book)

        with ta.book_verdict_memo():
            compare({"a": 1, None: 2})                    # ключи str+None: sort_keys падает
            compare({"a": 1, None: 2})
        self.assertEqual(len(calls), 2)

    def test_the_three_comparisons_and_censuses_are_wired(self):
        from spa_core.paper_trading import trim_optimum, trim_size_edge
        for fn in (ta.compare_trim_admissibility, trim_optimum.compare_trim_optimum,
                   trim_size_edge.compare_trim_size_edge, ta.trim_admissibility_census,
                   trim_optimum.trim_optimum_census, trim_size_edge.trim_size_edge_census):
            self.assertTrue(hasattr(fn, "__wrapped__"), fn.__qualname__)


class BridgeProcessScope(unittest.TestCase):
    def test_only_the_cli_path_of_the_bridge_enters_the_memory(self):
        src = (_REPO / "spa_core/monitoring/findings_bridge.py").read_text("utf-8")
        tree = ast.parse(src)
        main_block = [n for n in tree.body if isinstance(n, ast.If)
                      and "__main__" in ast.unparse(n.test)]
        self.assertEqual(len(main_block), 1)
        body = ast.unparse(main_block[0])
        self.assertIn("book_verdict_memo()", body)
        main_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        self.assertNotIn("book_verdict_memo", ast.unparse(main_fn))


def _old_book_shaped_writes(mod, rel, tree, literals):
    """Прежний обход (до perf/decision-loop) — эталон равенства ответа."""
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            continue
        binds = mod._assignments(fn)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else None)
            if name not in ("atomic_save", "write_text", "dump", "dumps"):
                continue
            payload = mod._resolve(node.args[0] if node.args else None, binds)
            if not isinstance(payload, ast.Dict):
                continue
            keys = {k.value for k in payload.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            hit = keys & {"positions", "book"}
            if not hit:
                continue
            value = next(v for k, v in zip(payload.keys, payload.values)
                         if isinstance(k, ast.Constant) and k.value in hit)
            origin_calls = mod._called_names(value, binds)
            if origin_calls & set(mod._DECIDERS):
                provenance, why = "DECIDES", sorted(origin_calls & set(mod._DECIDERS))
            elif origin_calls & set(mod._LOADERS):
                provenance, why = "DESCRIBES", sorted(origin_calls & set(mod._LOADERS))
            else:
                provenance, why = "UNKNOWN", sorted(origin_calls)[:6]
            targets = sorted(s for s in literals if s.endswith(".json"))
            out.append({"module": rel, "line": node.lineno, "writer": name,
                        "keys": sorted(keys), "provenance": provenance, "origin": why,
                        "artifact_candidates": targets, "resolved": bool(targets)})
    seen, uniq = set(), []
    for w in out:
        if w["line"] in seen:
            continue
        seen.add(w["line"])
        uniq.append(w)
    return uniq


class ProducerWalkUnchanged(unittest.TestCase):
    def test_the_walk_answers_like_the_old_one_on_real_sources(self):
        from spa_core.monitoring import cio_target_producers as ctp
        # население с настоящими сайтами (замер 03.11: 8 модулей во всём spa_core)
        # плюс каталог без них — обе ветки обхода
        files = [_REPO / p for p in (
            "spa_core/export_data.py", "spa_core/tuner/portfolio_rebalancer.py",
            "spa_core/monitoring/cio_kill_switch_controls.py",
            "spa_core/monitoring/cio_outcome_independence.py",
            "spa_core/backtesting/tier1/nav_proof.py")] + \
            sorted((_REPO / "spa_core/allocator").glob("*.py"))
        found = 0
        for path in files:
            tree = ast.parse(path.read_text("utf-8"))
            lits = ctp._string_constants(tree)
            rel = str(path.relative_to(_REPO))
            new = ctp._book_shaped_writes(rel, tree, lits)
            self.assertEqual(new, _old_book_shaped_writes(ctp, rel, tree, lits), rel)
            found += len(new)
        self.assertGreater(found, 0)                      # контроль: сайты на этом населении есть

    def test_nested_and_module_level_writers_are_still_found(self):
        from spa_core.monitoring import cio_target_producers as ctp
        src = ("import json\n"
               "atomic_save({'positions': allocate()}, 'a.json')\n"
               "def outer():\n"
               "    def inner():\n"
               "        book = _load_state()\n"
               "        json.dump({'book': book}, fh)\n"
               "    return inner\n"
               "def silent():\n"
               "    return 1\n")
        tree = ast.parse(src)
        lits = ctp._string_constants(tree)
        new = ctp._book_shaped_writes("p.py", tree, lits)
        self.assertEqual(new, _old_book_shaped_writes(ctp, "p.py", tree, lits))
        self.assertEqual([w["provenance"] for w in new], ["DECIDES", "DESCRIBES"])
        empty = ast.parse("def f():\n    return {'positions': 1}\n")
        self.assertEqual(ctp._book_shaped_writes("q.py", empty, set()), [])


if __name__ == "__main__":
    unittest.main()
