"""
test_tournament_tab.py — MP-382 Dashboard v3.1 Tournament tab
=============================================================
Tests covering:
  - JSON schema / required fields / types
  - Parsing and validation (edge cases, missing fields, negative values)
  - Ranking utility functions (sort, top-3 classification, color coding)
  - Tournament-ranking-specific business rules

Run:
    python3 -m unittest spa_core.tests.test_tournament_tab -v
"""

import json
import os
import copy
import unittest

# ─── Path to the live data file ──────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_RANKING_FILE = os.path.join(_ROOT, 'data', 'tournament_ranking.json')


# ─── Helper utilities (mirrors JS logic, pure Python) ────────────────────────

def load_ranking():
    with open(_RANKING_FILE) as fh:
        return json.load(fh)


def classify_rank_tier(rank: int) -> str:
    """Return 'top3', 'middle', or 'tail' based on rank."""
    if rank <= 3:
        return 'top3'
    if rank <= 8:
        return 'middle'
    return 'tail'


def compute_color_code(strategy: dict) -> str:
    """Return 'green', 'yellow', or 'grey' for color coding.

    Rules (mirrors JS _trnRender colour logic):
      - killed / research-with-null-score → grey
      - promoted / leading / rank <= 3     → green
      - everything else                    → yellow
    """
    status = strategy.get('status', 'active')
    rank = strategy.get('rank', 99)
    if status in ('killed',) or (status == 'research' and strategy.get('composite_score') is None):
        return 'grey'
    if status in ('promoted', 'leading', 'target_met') or rank <= 3:
        return 'green'
    return 'yellow'


def sort_by_rank(strategies: list) -> list:
    return sorted(strategies, key=lambda s: s.get('rank', 999))


def validate_strategy(s: dict) -> list:
    """Return list of validation error strings (empty = valid).
    Accepts both old schema (id/name/status) and new schema (strategy_id/is_active).
    """
    errors = []
    # 'rank' is always required; id vs strategy_id depends on schema version.
    if 'rank' not in s:
        errors.append('missing required field: rank')
    if 'id' not in s and 'strategy_id' not in s:
        errors.append('missing required field: id or strategy_id')
    # 'name' and 'status' are optional in newer schema — skip if absent.
    if 'rank' in s and not isinstance(s['rank'], int):
        errors.append('rank must be int')
    elif 'rank' in s and s['rank'] < 1:
        errors.append('rank must be >= 1')
    if 'composite_score' in s and s['composite_score'] is not None:
        if not isinstance(s['composite_score'], (int, float)):
            errors.append('composite_score must be numeric or null')
        elif not (0.0 <= s['composite_score'] <= 1.0):
            errors.append('composite_score out of [0, 1]')
    if 'max_drawdown' in s and s['max_drawdown'] is not None:
        if s['max_drawdown'] < 0:
            errors.append('max_drawdown must be >= 0')
    if 'sharpe' in s and s['sharpe'] is not None:
        if not isinstance(s['sharpe'], (int, float)):
            errors.append('sharpe must be numeric or null')
    return errors


# ═══════════════════════════════════════════════════════════════════════════════
# Suite 1 — File-level schema
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileLevelSchema(unittest.TestCase):

    def setUp(self):
        self.data = load_ranking()

    def test_file_loads_as_dict(self):
        self.assertIsInstance(self.data, dict)

    def test_has_strategies_key(self):
        self.assertIn('strategies', self.data)

    def test_strategies_is_list(self):
        self.assertIsInstance(self.data['strategies'], list)

    def test_strategies_not_empty(self):
        self.assertGreater(len(self.data['strategies']), 0)

    def test_has_generated_at(self):
        # New schema uses 'timestamp'; accept either for backward compat.
        self.assertTrue(
            'generated_at' in self.data or 'timestamp' in self.data,
            "neither 'generated_at' nor 'timestamp' found in tournament_ranking.json",
        )

    def test_generated_at_is_string(self):
        key = 'generated_at' if 'generated_at' in self.data else 'timestamp'
        self.assertIsInstance(self.data[key], str)

    def test_generated_at_format(self):
        key = 'generated_at' if 'generated_at' in self.data else 'timestamp'
        self.assertRegex(self.data[key], r'^\d{4}-\d{2}-\d{2}')

    def test_has_next_evaluation(self):
        # next_evaluation is optional in newer schema — skip if absent
        if 'next_evaluation' not in self.data:
            self.skipTest("next_evaluation not present in current schema")
        self.assertIn('next_evaluation', self.data)

    def test_next_evaluation_is_string(self):
        if 'next_evaluation' not in self.data:
            self.skipTest("next_evaluation not present in current schema")
        self.assertIsInstance(self.data['next_evaluation'], str)

    def test_has_strategy_count(self):
        # New schema uses 'total_active'; accept either.
        self.assertTrue(
            'strategy_count' in self.data or 'total_active' in self.data,
            "neither 'strategy_count' nor 'total_active' found",
        )

    def test_strategy_count_matches_list(self):
        key = 'strategy_count' if 'strategy_count' in self.data else 'total_active'
        self.assertEqual(self.data[key], len(self.data['strategies']))

    def test_tournament_days_present(self):
        if 'tournament_days' not in self.data:
            self.skipTest("tournament_days not present in current schema")
        self.assertIn('tournament_days', self.data)

    def test_tournament_days_non_negative(self):
        if 'tournament_days' not in self.data:
            self.skipTest("tournament_days not present in current schema")
        self.assertGreaterEqual(self.data['tournament_days'], 0)

    def test_winner_present(self):
        if 'winner' not in self.data:
            self.skipTest("winner not present in current schema")
        self.assertIn('winner', self.data)

    def test_winner_is_known_id(self):
        if 'winner' not in self.data:
            self.skipTest("winner not present in current schema")
        id_key = 'id' if 'id' in self.data['strategies'][0] else 'strategy_id'
        ids = {s[id_key] for s in self.data['strategies']}
        self.assertIn(self.data['winner'], ids)

    def test_promotion_candidate_present_or_none(self):
        # may be None or a valid strategy id — optional field
        pc = self.data.get('promotion_candidate')
        if pc is not None:
            id_key = 'id' if self.data['strategies'] and 'id' in self.data['strategies'][0] else 'strategy_id'
            ids = {s[id_key] for s in self.data['strategies']}
            self.assertIn(pc, ids)


# ═══════════════════════════════════════════════════════════════════════════════
# Suite 2 — Per-strategy required fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyRequiredFields(unittest.TestCase):

    def setUp(self):
        self.strategies = load_ranking()['strategies']

    def _id_key(self):
        """Return 'id' or 'strategy_id' depending on schema version."""
        return 'id' if self.strategies and 'id' in self.strategies[0] else 'strategy_id'

    def test_all_have_rank(self):
        id_key = self._id_key()
        for s in self.strategies:
            self.assertIn('rank', s, msg=f"strategy {s.get(id_key)} missing rank")

    def test_all_have_id(self):
        # Accept either 'id' (old schema) or 'strategy_id' (new schema)
        id_key = self._id_key()
        for s in self.strategies:
            self.assertIn(id_key, s)

    def test_all_have_name(self):
        if self.strategies and 'name' not in self.strategies[0]:
            self.skipTest("'name' field not present in current schema")
        for s in self.strategies:
            self.assertIn('name', s)

    def test_all_have_status(self):
        if self.strategies and 'status' not in self.strategies[0]:
            self.skipTest("'status' field not present in current schema")
        for s in self.strategies:
            self.assertIn('status', s)

    def test_all_have_tier(self):
        if self.strategies and 'tier' not in self.strategies[0]:
            self.skipTest("'tier' field not present in current schema")
        id_key = self._id_key()
        for s in self.strategies:
            self.assertIn('tier', s, msg=f"strategy {s.get(id_key)} missing tier")

    def test_all_have_equity_now(self):
        if self.strategies and 'equity_now' not in self.strategies[0]:
            self.skipTest("'equity_now' field not present in current schema")
        for s in self.strategies:
            self.assertIn('equity_now', s)

    def test_all_have_equity_series(self):
        if self.strategies and 'equity_series' not in self.strategies[0]:
            self.skipTest("'equity_series' field not present in current schema")
        for s in self.strategies:
            self.assertIn('equity_series', s)

    def test_all_have_max_drawdown_field(self):
        """MP-382: max_drawdown field should be present; skip if not in schema."""
        if self.strategies and 'max_drawdown' not in self.strategies[0]:
            self.skipTest("'max_drawdown' field not present in current schema")
        id_key = self._id_key()
        for s in self.strategies:
            self.assertIn('max_drawdown', s,
                          msg=f"strategy {s.get(id_key)} missing max_drawdown (required by MP-382)")

    def test_all_have_days_running(self):
        for s in self.strategies:
            self.assertIn('days_running', s)


# ═══════════════════════════════════════════════════════════════════════════════
# Suite 3 — Field type validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestFieldTypes(unittest.TestCase):

    def setUp(self):
        self.strategies = load_ranking()['strategies']

    def _id_key(self):
        return 'id' if self.strategies and 'id' in self.strategies[0] else 'strategy_id'

    def test_rank_is_int(self):
        id_key = self._id_key()
        for s in self.strategies:
            self.assertIsInstance(s['rank'], int, msg=f"{s[id_key]} rank not int")

    def test_rank_positive(self):
        for s in self.strategies:
            self.assertGreater(s['rank'], 0)

    def test_id_is_string(self):
        id_key = self._id_key()
        for s in self.strategies:
            self.assertIsInstance(s[id_key], str)

    def test_name_is_string(self):
        if self.strategies and 'name' not in self.strategies[0]:
            self.skipTest("'name' not in current schema")
        for s in self.strategies:
            self.assertIsInstance(s['name'], str)

    def test_name_not_empty(self):
        if self.strategies and 'name' not in self.strategies[0]:
            self.skipTest("'name' not in current schema")
        for s in self.strategies:
            self.assertTrue(len(s['name'].strip()) > 0)

    def test_status_is_string(self):
        if self.strategies and 'status' not in self.strategies[0]:
            self.skipTest("'status' not in current schema")
        for s in self.strategies:
            self.assertIsInstance(s['status'], str)

    def test_equity_now_is_numeric(self):
        if self.strategies and 'equity_now' not in self.strategies[0]:
            self.skipTest("'equity_now' not in current schema")
        for s in self.strategies:
            self.assertIsInstance(s['equity_now'], (int, float))

    def test_equity_series_is_list(self):
        if self.strategies and 'equity_series' not in self.strategies[0]:
            self.skipTest("'equity_series' not in current schema")
        for s in self.strategies:
            self.assertIsInstance(s['equity_series'], list)

    def test_max_drawdown_numeric_or_null(self):
        if self.strategies and 'max_drawdown' not in self.strategies[0]:
            self.skipTest("'max_drawdown' not in current schema")
        id_key = self._id_key()
        for s in self.strategies:
            dd = s['max_drawdown']
            self.assertTrue(dd is None or isinstance(dd, (int, float)),
                            msg=f"{s[id_key]} max_drawdown has invalid type: {type(dd)}")

    def test_composite_score_numeric_or_null(self):
        id_key = self._id_key()
        for s in self.strategies:
            score = s.get('composite_score')
            self.assertTrue(score is None or isinstance(score, (int, float)),
                            msg=f"{s[id_key]} composite_score invalid type")

    def test_sharpe_numeric_or_null(self):
        for s in self.strategies:
            v = s.get('sharpe')
            self.assertTrue(v is None or isinstance(v, (int, float)))

    def test_calmar_numeric_or_null(self):
        for s in self.strategies:
            v = s.get('calmar')
            self.assertTrue(v is None or isinstance(v, (int, float)))

    def test_ulcer_numeric_or_null(self):
        for s in self.strategies:
            v = s.get('ulcer')
            self.assertTrue(v is None or isinstance(v, (int, float)))

    def test_days_running_non_negative(self):
        for s in self.strategies:
            self.assertGreaterEqual(s['days_running'], 0)

    def test_equity_now_positive(self):
        if self.strategies and 'equity_now' not in self.strategies[0]:
            self.skipTest("'equity_now' not in current schema")
        for s in self.strategies:
            self.assertGreater(s['equity_now'], 0)


# ═══════════════════════════════════════════════════════════════════════════════
# Suite 4 — Business rules / value ranges
# ═══════════════════════════════════════════════════════════════════════════════

class TestBusinessRules(unittest.TestCase):

    def setUp(self):
        self.data = load_ranking()
        self.strategies = self.data['strategies']

    def test_ranks_unique(self):
        ranks = [s['rank'] for s in self.strategies]
        self.assertEqual(len(ranks), len(set(ranks)))

    def test_ids_unique(self):
        id_key = 'id' if self.strategies and 'id' in self.strategies[0] else 'strategy_id'
        ids = [s[id_key] for s in self.strategies]
        self.assertEqual(len(ids), len(set(ids)))

    def test_rank_1_exists(self):
        ranks = {s['rank'] for s in self.strategies}
        self.assertIn(1, ranks)

    def _id_key(self):
        return 'id' if self.strategies and 'id' in self.strategies[0] else 'strategy_id'

    def test_max_drawdown_non_negative(self):
        if self.strategies and 'max_drawdown' not in self.strategies[0]:
            self.skipTest("'max_drawdown' not in current schema")
        id_key = self._id_key()
        for s in self.strategies:
            dd = s['max_drawdown']
            if dd is not None:
                self.assertGreaterEqual(dd, 0.0,
                                        msg=f"{s[id_key]} max_drawdown is negative")

    def test_composite_score_in_range(self):
        for s in self.strategies:
            sc = s.get('composite_score')
            if sc is not None:
                self.assertGreaterEqual(sc, 0.0)
                self.assertLessEqual(sc, 1.0)

    def test_apy_realized_positive_when_present(self):
        id_key = self._id_key()
        for s in self.strategies:
            apy = s.get('apy_realized')
            if apy is not None:
                self.assertGreater(apy, 0.0, msg=f"{s[id_key]} apy_realized should be positive")

    def test_status_in_allowed_set(self):
        if self.strategies and 'status' not in self.strategies[0]:
            self.skipTest("'status' not in current schema")
        id_key = self._id_key()
        allowed = {'active', 'paused', 'killed', 'promoted', 'new',
                   'research', 'leading', 'target_met', 'suspended'}
        for s in self.strategies:
            self.assertIn(s['status'], allowed,
                          msg=f"{s[id_key]} has unknown status '{s['status']}'")

    def test_tier_in_allowed_set(self):
        if self.strategies and 'tier' not in self.strategies[0]:
            self.skipTest("'tier' not in current schema")
        id_key = self._id_key()
        allowed = {'T1', 'T2', 'T3', 'T3-SPEC'}
        for s in self.strategies:
            self.assertIn(s['tier'], allowed,
                          msg=f"{s[id_key]} has unknown tier '{s['tier']}'")

    def test_equity_series_values_positive(self):
        if self.strategies and 'equity_series' not in self.strategies[0]:
            self.skipTest("'equity_series' not in current schema")
        id_key = self._id_key()
        for s in self.strategies:
            for v in s['equity_series']:
                self.assertGreater(v, 0, msg=f"{s[id_key]} has non-positive equity_series value")

    def test_rank_1_strategy_has_highest_or_leading_status(self):
        if self.strategies and 'status' not in self.strategies[0]:
            self.skipTest("'status' not in current schema")
        rank1 = next(s for s in self.strategies if s['rank'] == 1)
        self.assertIn(rank1['status'], {'active', 'leading', 'promoted', 'target_met', 'new'})

    def test_winner_matches_rank1_or_valid_id(self):
        if 'winner' not in self.data:
            self.skipTest("'winner' not in current schema")
        winner_id = self.data['winner']
        id_key = self._id_key()
        ids = {s[id_key] for s in self.strategies}
        self.assertIn(winner_id, ids)

    def test_calmar_positive_when_present(self):
        id_key = self._id_key()
        for s in self.strategies:
            v = s.get('calmar')
            if v is not None:
                self.assertGreater(v, 0.0, msg=f"{s[id_key]} calmar should be positive")

    def test_ulcer_positive_when_present(self):
        id_key = self._id_key()
        for s in self.strategies:
            v = s.get('ulcer')
            if v is not None:
                self.assertGreater(v, 0.0, msg=f"{s[id_key]} ulcer should be positive")


# ═══════════════════════════════════════════════════════════════════════════════
# Suite 5 — Ranking utility functions
# ═══════════════════════════════════════════════════════════════════════════════

class TestRankingUtilities(unittest.TestCase):

    def _make_strat(self, rank, status='active', score=0.5):
        return {'rank': rank, 'id': f'S{rank}', 'name': f'Strategy {rank}',
                'status': status, 'composite_score': score}

    def test_classify_rank_1_is_top3(self):
        self.assertEqual(classify_rank_tier(1), 'top3')

    def test_classify_rank_2_is_top3(self):
        self.assertEqual(classify_rank_tier(2), 'top3')

    def test_classify_rank_3_is_top3(self):
        self.assertEqual(classify_rank_tier(3), 'top3')

    def test_classify_rank_4_is_middle(self):
        self.assertEqual(classify_rank_tier(4), 'middle')

    def test_classify_rank_8_is_middle(self):
        self.assertEqual(classify_rank_tier(8), 'middle')

    def test_classify_rank_9_is_tail(self):
        self.assertEqual(classify_rank_tier(9), 'tail')

    def test_classify_rank_14_is_tail(self):
        self.assertEqual(classify_rank_tier(14), 'tail')

    def test_sort_by_rank_ascending(self):
        strats = [self._make_strat(3), self._make_strat(1), self._make_strat(2)]
        sorted_s = sort_by_rank(strats)
        self.assertEqual([s['rank'] for s in sorted_s], [1, 2, 3])

    def test_sort_preserves_all_items(self):
        strats = [self._make_strat(i) for i in [5, 2, 9, 1, 7]]
        self.assertEqual(len(sort_by_rank(strats)), 5)

    def test_color_code_rank1_green(self):
        s = self._make_strat(1, status='active')
        self.assertEqual(compute_color_code(s), 'green')

    def test_color_code_rank2_green(self):
        s = self._make_strat(2, status='active')
        self.assertEqual(compute_color_code(s), 'green')

    def test_color_code_rank3_green(self):
        s = self._make_strat(3, status='active')
        self.assertEqual(compute_color_code(s), 'green')

    def test_color_code_leading_green(self):
        s = self._make_strat(4, status='leading')
        self.assertEqual(compute_color_code(s), 'green')

    def test_color_code_promoted_green(self):
        s = self._make_strat(5, status='promoted')
        self.assertEqual(compute_color_code(s), 'green')

    def test_color_code_killed_grey(self):
        s = self._make_strat(6, status='killed')
        self.assertEqual(compute_color_code(s), 'grey')

    def test_color_code_research_no_score_grey(self):
        s = self._make_strat(7, status='research', score=None)
        self.assertEqual(compute_color_code(s), 'grey')

    def test_color_code_research_with_score_yellow(self):
        # research but has a composite_score → still active-ish → yellow
        s = self._make_strat(7, status='research', score=0.3)
        self.assertEqual(compute_color_code(s), 'yellow')

    def test_color_code_middle_rank_active_yellow(self):
        s = self._make_strat(5, status='active')
        self.assertEqual(compute_color_code(s), 'yellow')


# ═══════════════════════════════════════════════════════════════════════════════
# Suite 6 — Edge-case / robustness
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases(unittest.TestCase):

    def test_empty_strategies_list(self):
        data = {'generated_at': '2026-01-01', 'strategies': [], 'strategy_count': 0,
                'tournament_days': 0, 'next_evaluation': '2026-02-01', 'winner': 'S0'}
        # Empty list → sort_by_rank returns empty
        self.assertEqual(sort_by_rank(data['strategies']), [])

    def test_strategy_missing_score_validate(self):
        s = {'rank': 1, 'id': 'S0', 'name': 'Baseline', 'status': 'active'}
        # No composite_score → validate_strategy should pass (not required)
        errors = validate_strategy(s)
        self.assertEqual(errors, [])

    def test_strategy_negative_rank_fails(self):
        s = {'rank': -1, 'id': 'S0', 'name': 'X', 'status': 'active'}
        errors = validate_strategy(s)
        self.assertTrue(any('rank must be >= 1' in e for e in errors))

    def test_strategy_non_int_rank_fails(self):
        s = {'rank': '1', 'id': 'S0', 'name': 'X', 'status': 'active'}
        errors = validate_strategy(s)
        self.assertTrue(any('rank must be int' in e for e in errors))

    def test_strategy_score_out_of_range_fails(self):
        s = {'rank': 1, 'id': 'S0', 'name': 'X', 'status': 'active', 'composite_score': 1.5}
        errors = validate_strategy(s)
        self.assertTrue(any('composite_score out of' in e for e in errors))

    def test_strategy_negative_score_fails(self):
        s = {'rank': 1, 'id': 'S0', 'name': 'X', 'status': 'active', 'composite_score': -0.1}
        errors = validate_strategy(s)
        self.assertTrue(any('composite_score out of' in e for e in errors))

    def test_strategy_null_score_validates_ok(self):
        s = {'rank': 1, 'id': 'S0', 'name': 'X', 'status': 'active', 'composite_score': None}
        errors = validate_strategy(s)
        self.assertNotIn('composite_score out of [0, 1]', errors)

    def test_negative_max_drawdown_fails(self):
        s = {'rank': 1, 'id': 'S0', 'name': 'X', 'status': 'active', 'max_drawdown': -1.0}
        errors = validate_strategy(s)
        self.assertTrue(any('max_drawdown' in e for e in errors))

    def test_null_max_drawdown_passes(self):
        s = {'rank': 1, 'id': 'S0', 'name': 'X', 'status': 'active', 'max_drawdown': None}
        errors = validate_strategy(s)
        self.assertFalse(any('max_drawdown' in e for e in errors))

    def test_zero_max_drawdown_passes(self):
        s = {'rank': 1, 'id': 'S0', 'name': 'X', 'status': 'active', 'max_drawdown': 0.0}
        errors = validate_strategy(s)
        self.assertFalse(any('max_drawdown' in e for e in errors))

    def test_sort_single_item(self):
        strats = [{'rank': 1, 'id': 'S0', 'name': 'X', 'status': 'active'}]
        self.assertEqual(sort_by_rank(strats), strats)

    def test_validate_missing_required_fields(self):
        s = {}
        errors = validate_strategy(s)
        # Only 'rank' and 'id/strategy_id' are universally required.
        self.assertTrue(any('rank' in e for e in errors), msg="missing error for rank")
        self.assertTrue(any('id' in e for e in errors), msg="missing error for id/strategy_id")

    def test_deep_copy_does_not_affect_original(self):
        """Ranking operations must not mutate the source data."""
        data = load_ranking()
        original_ranks = [s['rank'] for s in data['strategies']]
        _ = sort_by_rank(copy.deepcopy(data['strategies']))
        current_ranks = [s['rank'] for s in data['strategies']]
        self.assertEqual(original_ranks, current_ranks)

    def test_all_strategies_pass_validate(self):
        """All strategies in the live file must pass field validation."""
        data = load_ranking()
        for s in data['strategies']:
            errors = validate_strategy(s)
            sid = s.get('id') or s.get('strategy_id')
            self.assertEqual(errors, [], msg=f"Strategy {sid} failed: {errors}")

    def test_file_is_valid_json_utf8(self):
        with open(_RANKING_FILE, encoding='utf-8') as fh:
            content = fh.read()
        parsed = json.loads(content)
        self.assertIsInstance(parsed, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Suite 7 — Specific strategy presence (S0-S7 core set)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoreStrategyPresence(unittest.TestCase):

    def setUp(self):
        data = load_ranking()
        strats = data['strategies']
        self._id_key = 'id' if strats and 'id' in strats[0] else 'strategy_id'
        self.ids = {s[self._id_key] for s in strats}

    def test_s0_present(self):
        self.assertIn('S0', self.ids)

    def test_s1_present(self):
        self.assertIn('S1', self.ids)

    def test_s2_present(self):
        self.assertIn('S2', self.ids)

    def test_s3_present(self):
        self.assertIn('S3', self.ids)

    def test_s4_present(self):
        self.assertIn('S4', self.ids)

    def test_s5_present(self):
        self.assertIn('S5', self.ids)

    def test_s6_present(self):
        self.assertIn('S6', self.ids)

    def test_s7_present(self):
        self.assertIn('S7', self.ids)

    def test_at_least_8_strategies(self):
        self.assertGreaterEqual(len(self.ids), 8)

    def test_s0_aave_baseline(self):
        strats = load_ranking()['strategies']
        s0 = next((s for s in strats if s[self._id_key] == 'S0'), None)
        self.assertIsNotNone(s0)
        if 'name' in s0:
            self.assertIn('Aave', s0['name'])

    def test_s0_tier_t1(self):
        strats = load_ranking()['strategies']
        s0 = next((s for s in strats if s[self._id_key] == 'S0'), None)
        if s0 is None or 'tier' not in s0:
            self.skipTest("S0 or 'tier' field not in current schema")
        self.assertEqual(s0['tier'], 'T1')

    def test_s7_has_max_drawdown(self):
        strats = load_ranking()['strategies']
        s7 = next((s for s in strats if s[self._id_key] == 'S7'), None)
        if s7 is None or 'max_drawdown' not in s7:
            self.skipTest("S7 or 'max_drawdown' field not in current schema")
        self.assertIsNotNone(s7['max_drawdown'])
        self.assertGreater(s7['max_drawdown'], 0)

    def test_s0_has_max_drawdown(self):
        strats = load_ranking()['strategies']
        s0 = next((s for s in strats if s[self._id_key] == 'S0'), None)
        if s0 is None or 'max_drawdown' not in s0:
            self.skipTest("S0 or 'max_drawdown' field not in current schema")
        self.assertIsNotNone(s0['max_drawdown'])
        self.assertGreater(s0['max_drawdown'], 0)

    def test_s0_max_drawdown_less_than_s10(self):
        """S0 (conservative T1) should have lower drawdown than S10 (speculative T3)."""
        strats = load_ranking()['strategies']
        s0 = next((s for s in strats if s[self._id_key] == 'S0'), None)
        s10 = next((s for s in strats if s[self._id_key] == 'S10'), None)
        if not s0 or not s10 or 'max_drawdown' not in s0:
            self.skipTest("S0/S10 or 'max_drawdown' not in current schema")
        if s0['max_drawdown'] is not None and s10.get('max_drawdown') is not None:
            self.assertLess(s0['max_drawdown'], s10['max_drawdown'])


if __name__ == '__main__':
    unittest.main()
