"""Оболочка v1.3 и независимая сверка.

Главный тест здесь — последний: сверка обязана НЕ ИМПОРТИРОВАТЬ ничего из кокпита.
Проверка, зовущая проверяемый код, отвечает на вопрос «воспроизводим ли он», а не
«верен ли он», и именно так v1.2 «подтвердила» просадку, которой не было.
"""
import ast
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARTO = ROOT / 'scripts' / 'cartographer'
sys.path.insert(0, str(CARTO))

import director_shell as DS        # noqa: E402
import director_verify as DV       # noqa: E402
import web_shell as WS             # noqa: E402

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

COCKPIT_MODULES = {
    'owner_facts', 'capital_truth', 'director_facts', 'service_health',
    'bridge_evidence', 'build_stages', 'owner_decisions', 'director_v13',
    'director_shell', 'web_shell', 'web_projection', 'director_publish',
}


def minimal_projection():
    return {
        'generated_at': '2026-09-21T12:00:00+00:00',
        'semantic_digest': 'abc', 'redaction_stats': {},
        'layers': {'CAPITAL': {}, 'STUDIO': {}, 'BUILD': {}},
        'v13': {
            'fact_digest': 'deadbeef',
            'capital': {'schema': 'director_facts/1', 'facts': [], 'mode': 'PAPER',
                        'currency': None, 'history_quality': {}, 'positions': [],
                        'target': {'state': 'NOT_MEASURED'}, 'policy': {'state': 'NOT_MEASURED'},
                        'attention': {'portfolio_attention': [],
                                      'portfolio_attention_count': 0,
                                      'watchlist_rnd': [], 'not_relevant': [],
                                      'admission_rule': 'правило'},
                        'series_rows': []},
            'service_health': {'counts': {}, 'entities': [], 'problems': [],
                               'problems_retired': [], 'by_kind': {},
                               'by_schedule_class': {},
                               'health_contract_note': 'контракта нет'},
            'owner_decisions': {'items': [], 'sources': [], 'subject_vocabulary': {}},
            'bridge': {'state': 'NOT_MEASURED', 'reason': 'не подан'},
            'pipeline': {'stages': [], 'counts': {}, 'autonomy_breaks_at': None},
        },
    }


class ShellContract(unittest.TestCase):
    def setUp(self):
        self.page = DS.shell_html(minimal_projection())

    def test_page_passes_its_own_contract(self):
        DS.validate_shell(self.page, 'test')

    def test_inherits_the_v11_contract(self):
        WS.validate_shell(self.page, 'test')

    def test_no_buttons_forms_or_network(self):
        for bad in ('<button', '<form', 'onclick=', 'fetch(', 'XMLHttpRequest',
                    'serviceWorker', 'src="http', 'href="http'):
            self.assertNotIn(bad, self.page, f'оболочка содержит {bad}')

    def test_exactly_three_views(self):
        self.assertEqual(self.page.count('class="view"'), 3)

    def test_two_drawdowns_are_named_apart(self):
        # ДЕФЕКТ v1.2: одно слово «просадка» на две разные величины.
        self.assertIn('МАКСИМАЛЬНАЯ просадка', self.page)
        self.assertIn('просадка СЕЙЧАС', self.page)

    def test_currency_is_never_attributed_by_the_screen(self):
        for phrase, _why in DS.FORBIDDEN_PHRASES:
            self.assertNotIn(phrase, self.page)

    def test_real_policy_stays_on_the_page(self):
        self.assertIn('REAL CAPITAL: NOT PROVEN', self.page)

    def test_create_stays_disabled(self):
        self.assertIn('ПОКА НЕ ВКЛЮЧЕНО', self.page)

    def test_validator_refuses_a_page_missing_the_split_drawdowns(self):
        # Положительный контроль самого контракта: он обязан краснеть.
        broken = self.page.replace('МАКСИМАЛЬНАЯ просадка', 'просадка')
        with self.assertRaises(WS.ShellError):
            DS.validate_shell(broken, 'test')

    def test_validator_refuses_the_invented_currency_phrase(self):
        phrase = DS.FORBIDDEN_PHRASES[0][0]
        broken = self.page.replace('</footer>', f'{phrase}</footer>')
        with self.assertRaises(WS.ShellError):
            DS.validate_shell(broken, 'test')


class ChartHonesty(unittest.TestCase):
    def test_gap_breaks_the_line_instead_of_joining_it(self):
        rows = [{'date': '2026-01-01', 'close_equity': 100.0, 'evidenced': True},
                {'date': '2026-01-02', 'close_equity': 101.0, 'evidenced': True},
                {'date': '2026-01-04', 'close_equity': 102.0, 'evidenced': True}]
        svg = DS.equity_chart(rows, quality={'missing_dates': ['2026-01-03'],
                                             'series_boundaries': []})
        self.assertIn('gapmark', svg)
        self.assertGreaterEqual(svg.count('<polyline'), 2)

    def test_unverified_segment_is_drawn_differently(self):
        rows = [{'date': '2026-01-01', 'close_equity': 100.0, 'evidenced': False},
                {'date': '2026-01-02', 'close_equity': 101.0, 'evidenced': False},
                {'date': '2026-01-03', 'close_equity': 102.0, 'evidenced': True},
                {'date': '2026-01-04', 'close_equity': 103.0, 'evidenced': True}]
        svg = DS.equity_chart(rows, quality={'missing_dates': [], 'series_boundaries': []})
        self.assertIn('class="unver"', svg)
        self.assertIn('class="evid"', svg)

    def test_one_point_is_not_a_chart(self):
        svg = DS.equity_chart([{'date': '2026-01-01', 'close_equity': 1.0}],
                              quality={})
        self.assertIn('график не строится', svg)


class VerifierIndependence(unittest.TestCase):
    """Самый важный тест файла."""

    def test_verifier_imports_no_cockpit_module(self):
        tree = ast.parse((CARTO / 'director_verify.py').read_text(encoding='utf-8'))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split('.')[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        leaked = imported & COCKPIT_MODULES
        self.assertEqual(leaked, set(),
                         f'сверка импортирует проверяемый код: {sorted(leaked)}. '
                         f'Тогда она отвечает на вопрос о воспроизводимости, '
                         f'а не о верности')

    def test_stable_and_volatile_sets_do_not_overlap(self):
        self.assertEqual(DV.STABLE_METRICS & DV.VOLATILE_METRICS, set())

    def test_unclassified_metric_fails_the_release(self):
        # Молча отнести новое число к «изменчивым» — значит открыть дверь любому
        # расхождению. Неклассифицированная величина обязана ронять выпуск.
        result = DV.compare({'facts': [{'metric': 'совсем_новое', 'value': 1}]},
                            {'совсем_новое': 2})
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertIn('совсем_новое', result['unclassified_metrics'])

    def test_stable_mismatch_fails(self):
        result = DV.compare({'facts': [{'metric': 'equity_now', 'value': 1.0}]},
                            {'equity_now': 2.0})
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(result['mismatches'], 1)

    def test_stable_agreement_passes(self):
        result = DV.compare({'facts': [{'metric': 'equity_now', 'value': 1.0}]},
                            {'equity_now': 1.0})
        self.assertEqual(result['verdict'], 'PASS')

    def test_volatile_difference_is_reported_but_does_not_fail(self):
        result = DV.compare({'service_health': {'counts': {'has_live_process': 9}}},
                            {'running_now': 8})
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['volatile_differences'], 1)
        self.assertEqual(result['rows'][0]['verdict'], 'VOLATILE_DIFFERS')


if __name__ == '__main__':
    unittest.main()
