"""Тесты информационного покрытия Director OS v1.2.

Предмет — не «данные появились», а что появление НЕ стоило честности:
  · ряд остаётся рядом, а снимок не выдаётся за историю;
  · род службы выводится из наблюдения, и слово «агент» не присваивается никому;
  · «не измерено» не превращается в ноль ни в одном новом поле;
  · два реестра работ не складываются;
  · политика REAL не ослаблена ни на йоту.
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cartographer import web_projection as wp  # noqa: E402
from scripts.cartographer import web_shell as ws  # noqa: E402


def _history(points=5, **kw):
    daily = [{'date': f'2026-09-{i+1:02d}', 'equity': 100000.0 + i * 10,
              'cumulative_return_pct': i * 0.01, 'drawdown_pct': -0.01 * i,
              'daily_return_pct': 0.01, 'evidenced': True} for i in range(points)]
    base = {'daily': daily, 'summary': {'num_days': points, 'evidenced_days': points,
                                        'start_equity': 100000.0,
                                        'end_equity': 100000.0 + (points - 1) * 10,
                                        'total_return_pct': 0.05,
                                        'max_drawdown_pct': -0.04},
            'metrics_history': [], 'mode': 'read_only_simulation',
            'mode_basis': 'режим объявлен источником'}
    base.update(kw)
    return base


def _services(n=3):
    return {'entities': [
        {'id': 'com.spa.alpha', 'status': 'LIVE', 'role': 'monitoring',
         'layer': 'product', 'intent': 'active', 'schedule': 'interval:300s',
         'last_exit': 0, 'stages': {'DECLARED': True, 'LOADED': True,
                                    'RUNNING': True, 'HEALTHY': None}},
        {'id': 'com.spa.beta', 'status': 'DEGRADED', 'role': 'infra',
         'layer': 'infra', 'intent': 'active', 'schedule': 'daemon',
         'stages': {'DECLARED': True, 'HEALTHY': None}},
        {'id': 'com.spa.gamma', 'status': 'LEGACY', 'role': 'other',
         'intent': 'retired', 'schedule': None, 'stages': {}},
    ][:n]}


def _proj(**kw):
    inv = {'real_capital_proven': False, 'real_capital_note': 'не доказан',
           'capital_by_mode': {'REAL': None, 'PAPER': 100.0},
           'capital_metrics': [], 'kill_switch': {'triggered': False},
           'golive': {'ready': True, 'passed': 29, 'total': 29},
           'rnd_stage_counts': {}, 'counts': {'objects': 3}, 'objects': [],
           'limits': []}
    return wp.build_projection(investments=inv, actions={
        'counts': {'candidates': 0, 'ready_for_ui': 0, 'not_ready': 0, 'red_zone': 13},
        'red_zone': ['move_capital'], 'required_properties': [],
        'ui_exposes_actions': False, 'actions': []}, **kw)


class HistoryIsNeverManufactured(unittest.TestCase):

    def test_a_real_series_is_marked_as_a_series(self):
        p = _proj(capital_history=_history(5))
        h = p['layers']['CAPITAL']['history']
        self.assertEqual(h['state'], 'READ')
        self.assertTrue(h['is_a_series'])
        self.assertEqual(h['daily_points'], 5)

    def test_a_single_point_is_not_a_series(self):
        """Снимок историей не становится — это правило, а не осторожность."""
        p = _proj(capital_history=_history(1))
        self.assertFalse(p['layers']['CAPITAL']['history']['is_a_series'])

    def test_an_absent_history_is_NOT_MEASURED_not_empty(self):
        p = _proj()
        h = p['layers']['CAPITAL']['history']
        self.assertEqual(h['state'], 'NOT_MEASURED')
        self.assertIn('НЕ значит', h['note'])

    def test_the_chart_refuses_to_draw_from_one_point(self):
        out = ws._sparkline([1.0])
        self.assertIn('не строится', out)
        self.assertNotIn('<svg', out)

    def test_the_chart_draws_from_two_points(self):
        out = ws._sparkline([1.0, 2.0])
        self.assertIn('<svg', out)
        self.assertIn('polyline', out)

    def test_the_chart_needs_no_network(self):
        out = ws._sparkline([1.0, 2.0, 3.0])
        for bad in ('http', 'cdn', 'script', 'fetch'):
            self.assertNotIn(bad, out)

    def test_return_windows_without_depth_are_not_zero(self):
        """Нет глубины ряда — «не измерено», а не 0 %."""
        windows = ws._return_windows(_history(3)['daily'])
        self.assertIsNotNone(windows['d1'])
        self.assertIsNone(windows['d7'])
        self.assertIsNone(windows['d30'])

    def test_the_page_says_not_measured_for_absent_windows(self):
        page = ws.shell_html(_proj(capital_history=_history(3)))
        block = page.split('за 7 дней', 1)[0][-260:]
        self.assertIn('не измерено', block)


class ServicesAreClassifiedNotRenamedAgents(unittest.TestCase):

    def test_the_word_agent_is_assigned_to_nobody(self):
        """Метка менеджера процессов агентом не является — требование ARB."""
        p = _proj(services=_services())
        kinds = {s['kind'] for s in p['layers']['STUDIO']['services']['services']}
        self.assertNotIn('AGENT', kinds)
        self.assertIn('агент', p['layers']['STUDIO']['services']['agent_note'])

    def test_kind_is_derived_from_observed_schedule(self):
        self.assertEqual(wp.service_kind('daemon'), 'DAEMON')
        self.assertEqual(wp.service_kind('interval:300s'), 'SCHEDULED')
        self.assertEqual(wp.service_kind('calendar:08:00'), 'SCHEDULED')
        self.assertEqual(wp.service_kind('manual'), 'MANUAL')

    def test_an_unknown_schedule_is_UNKNOWN_not_a_guess(self):
        for value in (None, '', 'что-то новое'):
            self.assertEqual(wp.service_kind(value), 'UNKNOWN')

    def test_the_launchd_label_becomes_a_service_name(self):
        p = _proj(services=_services())
        names = [s['name'] for s in p['layers']['STUDIO']['services']['services']]
        self.assertIn('alpha', names)
        for n in names:
            self.assertNotIn('com.spa.', n)

    def test_unmeasured_health_is_counted_separately_from_unhealthy(self):
        p = _proj(services=_services())
        svc = p['layers']['STUDIO']['services']
        self.assertEqual(svc['health_measured'], 0)
        self.assertEqual(svc['health_not_measured'], svc['count'])

    def test_the_stage_word_says_not_measured_rather_than_no(self):
        self.assertEqual(ws._stage_word({}), 'не измерено')
        self.assertEqual(ws._stage_word(None), 'не измерено')
        self.assertIn('далее не измерено',
                      ws._stage_word({'DECLARED': True, 'HEALTHY': None}))

    def test_absent_services_are_NOT_MEASURED(self):
        self.assertEqual(_proj()['layers']['STUDIO']['services']['state'],
                         'NOT_MEASURED')


class TwoRegistriesAreNeverSummed(unittest.TestCase):

    def test_the_page_states_that_registries_do_not_add_up(self):
        work = {'counts': {'waiting_owner': 2, 'in_progress': 5,
                           'by_source_state': {'tracker': 693, 'kanban': 884}},
                'identity': {'proven_unique_work_count': None,
                             'proven_unique_reason': 'не измерено'}, 'limits': []}
        page = ws.shell_html(_proj(work=work))
        self.assertIn('не складываются', page)

    def test_an_unproven_unique_count_is_not_measured_on_screen(self):
        work = {'counts': {}, 'identity': {'proven_unique_work_count': None,
                                           'proven_unique_reason': 'нет'}, 'limits': []}
        page = ws.shell_html(_proj(work=work))
        block = page.split('уникальных работ доказано', 1)[1].split('</div>', 2)
        self.assertIn('не измерено', ''.join(block[:2]))


class PipelineShowsWhereAutonomyStops(unittest.TestCase):

    PIPE = [{'stage': 'Приём', 'state': 'LIVE', 'basis': 'a'},
            {'stage': 'Архитектор', 'state': 'DOCUMENTED_ONLY', 'basis': 'b'},
            {'stage': 'Доставка', 'state': 'LIVE', 'basis': 'c'}]

    def test_the_first_non_live_stage_is_named(self):
        p = _proj(pipeline=self.PIPE)
        self.assertEqual(p['layers']['BUILD']['pipeline']['autonomy_stops_at'],
                         'Архитектор')

    def test_an_unknown_state_is_not_silently_accepted(self):
        p = _proj(pipeline=[{'stage': 'x', 'state': 'ВЫДУМАННОЕ', 'basis': 'y'}])
        self.assertEqual(p['layers']['BUILD']['pipeline']['stages'][0]['state'],
                         'UNKNOWN')

    def test_all_live_means_no_stop(self):
        p = _proj(pipeline=[{'stage': 'a', 'state': 'LIVE', 'basis': 'x'}])
        self.assertIsNone(p['layers']['BUILD']['pipeline']['autonomy_stops_at'])

    def test_an_absent_pipeline_is_NOT_MEASURED(self):
        self.assertEqual(_proj()['layers']['BUILD']['pipeline']['state'], 'NOT_MEASURED')

    def test_the_page_shows_the_stop_to_the_owner(self):
        page = ws.shell_html(_proj(pipeline=self.PIPE))
        self.assertIn('Автономия останавливается на', page)
        self.assertIn('Архитектор', page)


class CapacityAndReleaseRegistryStayHonest(unittest.TestCase):

    def test_capacity_is_declared_not_measured_on_screen(self):
        page = ws.shell_html(_proj())
        self.assertIn('Ёмкость Claude и вычислений: НЕ ИЗМЕРЕНО', page)
        self.assertIn('значило бы выдумать', page)

    def test_release_registry_is_declared_absent(self):
        page = ws.shell_html(_proj())
        self.assertIn('РЕЕСТРА НЕ СУЩЕСТВУЕТ', page)

    def test_memory_systems_are_shown_as_several_not_one(self):
        mem = {'state': 'PARTIAL', 'systems': [
            {'name': 'A', 'state': 'LIVE', 'note': 'x'},
            {'name': 'B', 'state': 'PARTIAL', 'note': 'y'}],
            'note': 'связи не измерены'}
        page = ws.shell_html(_proj(memory=mem))
        self.assertIn('Память: PARTIAL', page)
        self.assertIn('связи не измерены', page)


class NothingNewWeakensTheWebSafePolicy(unittest.TestCase):

    def test_the_real_policy_is_unchanged(self):
        self.assertEqual(wp.REAL_WEB_POLICY['WALLET_ACCOUNT_IDENTIFIER'], 'NEVER')
        for cls in ('REAL_CAPITAL_SUMMARY', 'REAL_POSITION_DETAIL',
                    'RAW_INVESTMENT_EVIDENCE'):
            self.assertEqual(wp.REAL_WEB_POLICY[cls], 'BLOCKED')

    def test_a_wallet_inside_a_position_is_dropped(self):
        pos = {'capital_usd': 100.0, 'execution_mode': 'paper',
               'positions_detail': {'p': {'usd': 100.0, 'wallet': '0x' + 'a' * 40}}}
        p = _proj(positions=pos)
        payload = json.dumps(p, ensure_ascii=False)
        self.assertNotIn('0x' + 'a' * 40, payload)
        wp.validate_projection(p, 'test')

    def test_a_new_unclassified_fields_VALUE_is_blocked(self):
        """Блокируется ЗНАЧЕНИЕ. Имя остаётся в перечне удержанного — намеренно."""
        p = _proj(services={'entities': [{'id': 'com.spa.x', 'status': 'LIVE',
                                          'совершенно_новое_поле': 'тайна'}]})
        payload = json.dumps(p, ensure_ascii=False)
        self.assertNotIn('тайна', payload)
        service = p['layers']['STUDIO']['services']['services'][0]
        self.assertNotIn('совершенно_новое_поле', service)

    def test_the_blocked_list_is_published_on_purpose(self):
        """Без перечня удержанного умолчание «не публиковать» непроверяемо."""
        p = _proj(services={'entities': [{'id': 'com.spa.x', 'status': 'LIVE',
                                          'совершенно_новое_поле': 'тайна'}]})
        self.assertIn('совершенно_новое_поле', p['unknown_keys_blocked'])

    def test_a_telling_field_NAME_is_redacted_in_that_list(self):
        """Имя поля тоже бывает говорящим: секрет и путь вырезаются и из имени."""
        p = _proj(services={'entities': [
            {'id': 'com.spa.x', 'status': 'LIVE',
             'GITHUB_PAT_SPA': 1, '/Users/someone/Documents/SPA_Claude/x': 2}]})
        blocked = ' '.join(p['unknown_keys_blocked'])
        self.assertNotIn('GITHUB_PAT_SPA', blocked)
        self.assertNotIn('/Users/someone', blocked)

    def test_the_built_projection_still_passes_the_contract(self):
        p = _proj(capital_history=_history(), services=_services(),
                  pipeline=[{'stage': 'a', 'state': 'LIVE', 'basis': 'b'}])
        self.assertTrue(wp.validate_projection(p, 'test'))

    def test_non_finite_numbers_are_named_not_lost(self):
        """`promotion_report.json` содержит -Infinity; JSON такого значения не имеет."""
        promo = {'decisions': [{'strategy_id': 'S', 'action': 'demote',
                                'metrics': {'sharpe_30d': float('-inf')}}]}
        p = _proj(promotion=promo)
        payload = json.dumps(p, ensure_ascii=False, allow_nan=False)
        self.assertIn('non_finite', payload)


class ThePageStaysSmallAndSelfContained(unittest.TestCase):

    def _page(self):
        return ws.shell_html(_proj(capital_history=_history(120),
                                   services=_services(),
                                   pipeline=[{'stage': 'a', 'state': 'LIVE', 'basis': 'b'}]))

    def test_a_120_point_series_does_not_explode_the_dom(self):
        """Ряд рисуется ОДНИМ путём SVG, а не 120 узлами."""
        page = self._page()
        self.assertLess(page.count('<div'), 400)
        self.assertLessEqual(page.count('<svg class="spark"'), 4)

    def test_still_no_button_form_or_network(self):
        page = self._page()
        for bad in ('<button', '<form', 'onclick=', 'fetch(', 'serviceWorker'):
            self.assertNotIn(bad, page)
        self.assertEqual(re.findall(r'(?:src|href)="(?:https?:)?//', page), [])

    def test_exactly_three_layers_remain(self):
        page = self._page()
        self.assertEqual(page.count('class="view"'), 3)
        ws.validate_shell(page, 'test')

    def test_details_are_closed_by_default(self):
        """Подробности прячутся: экран владельца — не выгрузка."""
        page = self._page()
        self.assertIn('<details class="drill">', page)
        self.assertNotIn('<details class="drill" open', page)


if __name__ == '__main__':
    unittest.main()
