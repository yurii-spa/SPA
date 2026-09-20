"""Тесты закрытой оболочки владельца (v1.1 Epic 1).

Предмет проверки — не «страница отрисовалась», а четыре обещания, данных ARB:
  1. слоёв ровно три и они не смешиваются;
  2. действий нет ни одного, и «Создать» помечен невключённым;
  3. недоказанное не выдаётся за доказанное (REAL-капитал, Архитектор, CIO);
  4. страница самодостаточна: ни сети, ни service worker'а, ни внешних ссылок.
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


def _projection(**kw):
    inv = {
        'real_capital_proven': False,
        'real_capital_note': 'ни один источник не объявил режим REAL поимённо',
        'capital_by_mode': {'REAL': None, 'PAPER': 101340.69, 'SHADOW': None},
        'capital_metrics': [{'metric_type': 'CURRENT_EQUITY', 'mode': 'PAPER',
                             'value': 101340.69, 'currency': 'USDC'}],
        'kill_switch': {'triggered': False, 'reason': 'all clear'},
        'golive': {'ready': True, 'passed': 29, 'total': 29},
        'rnd_stage_counts': {'PAPER_CANDIDATE': 4, 'REJECT': 6},
        'counts': {'objects': 81, 'by_mode': {'PAPER': 70, 'RND': 11}},
        'limits': ['капитал режима REAL не доказан'],
    }
    inv.update(kw.pop('investments', {}))
    rel = {'counts': {'active_confirmed': 52, 'active_unverified': 222,
                      'by_classification': {'INCIDENT': 80, 'CONDITION': 225},
                      'by_severity': {'CRITICAL': 12, 'WARNING': 149}},
           'findings': [], 'limits': []}
    work = {'counts': {'waiting_owner': 2, 'blocked': 1, 'in_progress': 77,
                       'by_owner_view_state': {'IN_PROGRESS': 77}},
            'identity': {'proven_unique_work_count': None, 'proven_unique_reason': 'не измерено'},
            'limits': []}
    gov = {'counts': {'owner_gated': 12, 'adr_number_collisions': 7,
                      'backups_observed': 3, 'recovery_tested': 1,
                      'by_recovery_status': {'DOCUMENTED_UNTESTED': 7, 'TESTED': 1}},
           'limits': []}
    director = {'system_state': 'ТРЕБУЕТ ВНИМАНИЯ', 'system_state_reason': 'есть незакрытое',
                'has_health_score': False,
                'blocks': {'owner_decisions': {'shown': 2, 'count': 2,
                                                   'empty_means': 'карточек нет'},
                           'attention_now': {'shown': 5, 'count': 34,
                                             'empty_means': 'подтверждённых нет'}}}
    actions = {'counts': {'candidates': 5, 'ready_for_ui': 0, 'not_ready': 5, 'red_zone': 13},
               'red_zone': ['move_capital', 'execute_trade'],
               'required_properties': ['audit_record'], 'ui_exposes_actions': False,
               'actions': [{'action': 'rebuild_portal', 'verdict': 'NOT_READY_FOR_UI',
                            'destructive': False, 'missing_properties': ['audit_record']}]}
    bridge = {'state': 'LIVE', 'repo': 'studio_bridge',
              'daemons': {'coordinator': 'работает'},
              'db': {'tasks': 11, 'artifacts': 0}, 'code': {'lines': 42767},
              'note': 'сквозная проходимость НЕ измерена'}
    intake = [{'intake_kind': 'VOICE', 'available': True, 'note': 'голосовое в Telegram'},
              {'intake_kind': 'SCREENSHOT', 'available': False, 'note': 'не найдено'}]
    return wp.build_projection(investments=inv, reliability=rel, work=work,
                               governance=gov, director=director, actions=actions,
                               bridge=bridge, intake=intake, **kw)


ARCHITECT = {'state': 'DOCUMENTED_ONLY', 'note': 'документы есть, реализации не найдено'}
CIO = {'state': 'DOCUMENTED_ONLY', 'note': 'описаны 16 аналитиков; агента нет'}


def _page(**kw):
    p = kw.pop('projection', None) or _projection()
    bridge = (p['layers']['BUILD'] or {}).get('bridge')
    return ws.shell_html(p, architect=kw.pop('architect', ARCHITECT),
                         cio=kw.pop('cio', CIO),
                         bridge=bridge if isinstance(bridge, dict) else None, **kw)


class ThreeLayersAndNoFourth(unittest.TestCase):

    def test_exactly_three_views_exist(self):
        page = _page()
        self.assertEqual(page.count('class="view"'), 3)
        for slug in ('capital', 'studio', 'build'):
            self.assertIn(f'id="view-{slug}"', page)

    def test_every_layer_has_a_tab_and_the_owner_question(self):
        page = _page()
        for slug, title, _icon, question in ws.LAYERS:
            self.assertIn(f'href="#{slug}"', page)
            self.assertIn(title, page)
            self.assertIn(question, page)

    def test_the_contract_refuses_a_page_missing_a_layer(self):
        page = _page().replace('id="view-build"', 'id="view-gone"')
        with self.assertRaises(ws.ShellError) as caught:
            ws.validate_shell(page, 'test')
        self.assertIn('build', str(caught.exception))

    def test_the_contract_refuses_a_fourth_view(self):
        page = _page().replace('</main>', '<div class="view" id="view-misc"></div></main>')
        with self.assertRaises(ws.ShellError) as caught:
            ws.validate_shell(page, 'test')
        self.assertIn('ровно три', str(caught.exception))

    def test_capital_and_studio_content_do_not_bleed_into_one_view(self):
        """Слои — граница: блок капитала не должен оказаться внутри вида студии."""
        page = _page()
        studio = page.split('id="view-studio"', 1)[1].split('id="view-build"', 1)[0]
        self.assertNotIn('Капитал по режимам', studio)
        self.assertNotIn('REAL CAPITAL', studio)


class NoActionsAtAll(unittest.TestCase):

    def test_there_is_no_button_and_no_form(self):
        page = _page()
        self.assertNotIn('<button', page)
        self.assertNotIn('<form', page)
        self.assertNotIn('onclick=', page)

    def test_create_is_shown_but_marked_not_enabled(self):
        page = _page()
        self.assertIn('Создать', page)
        self.assertIn('ПОКА НЕ ВКЛЮЧЕНО', page)

    def test_create_is_not_an_interactive_element(self):
        """Нечего нажать — значит нечего и исполнить."""
        page = _page()
        create = page.split('class="create"', 1)[1].split('</section>', 1)[0]
        for tag in ('<button', '<a ', '<input', 'onclick', 'href='):
            self.assertNotIn(tag, create)

    def test_the_contract_refuses_a_smuggled_button(self):
        page = _page().replace('</main>', '<button>Запустить</button></main>')
        with self.assertRaises(ws.ShellError) as caught:
            ws.validate_shell(page, 'test')
        self.assertIn('<button>', str(caught.exception))

    def test_the_contract_refuses_an_onclick(self):
        page = _page().replace('<main>', '<main onclick="go()">')
        with self.assertRaises(ws.ShellError):
            ws.validate_shell(page, 'test')

    def test_a_block_total_is_a_real_number_not_not_measured(self):
        """Настоящая ошибка сборки: полное число лежит в `count`, а брался `total`.

        Владелец видел «показано 5 из не измерено» — формально честно, практически
        бесполезно. Контроль обязан краснеть, если ключ снова разъедется.
        """
        page = _page()
        table = page.split('Что требует внимания', 1)[1].split('</table>', 1)[0]
        row = table.split('Требует внимания сейчас', 1)[1].split('</tr>', 1)[0]
        self.assertIn('>34<', row)
        self.assertNotIn('не измерено', row)

    def test_blocks_are_named_in_the_owners_language_not_in_slugs(self):
        """«owner-first» и developer dashboard различаются именно здесь."""
        page = _page()
        table = page.split('Что требует внимания', 1)[1].split('</table>', 1)[0]
        self.assertIn('Нужно моё решение', table)
        self.assertNotIn('owner_decisions', table)
        self.assertNotIn('attention_now', table)

    def test_an_unknown_block_slug_is_shown_as_is_not_invented(self):
        """Выдумать название незнакомому блоку — то же, что перевести непонятое."""
        p = _projection()
        p['layers']['STUDIO']['blocks']['brand_new_block'] = {'shown': 1, 'count': 9}
        page = _page(projection=p)
        self.assertIn('brand_new_block', page)

    def test_build_explains_why_there_are_no_buttons_with_numbers(self):
        page = _page()
        build = page.split('id="view-build"', 1)[1]
        self.assertIn('Почему кнопок нет', build)
        self.assertIn('готовы для UI', build)


class NothingUnprovenIsPresentedAsProven(unittest.TestCase):

    def test_unproven_real_capital_is_stated_in_the_headline(self):
        self.assertIn('REAL CAPITAL: NOT PROVEN', _page())

    def test_a_null_mode_reads_as_not_measured_not_as_zero(self):
        """Инвариант #17 на экране: пустое наблюдение не должно выглядеть нулём."""
        page = _page()
        capital = page.split('id="view-capital"', 1)[1].split('id="view-studio"', 1)[0]
        modes = capital.split('class="modes"', 1)[1].split('</div></section>', 1)[0]
        real = modes.split('>REAL<', 1)[1].split('</div>', 1)[0]
        self.assertIn('не измерено', real)
        self.assertNotIn('0,00', real)

    def test_a_proven_real_capital_drops_the_headline(self):
        """Обратный контроль: надпись обязана исчезать, иначе она декорация."""
        p = _projection(investments={'real_capital_proven': True})
        self.assertNotIn('REAL CAPITAL: NOT PROVEN', _page(projection=p))

    def test_architect_and_cio_are_shown_as_documented_only(self):
        page = _page()
        self.assertIn('Архитектор: DOCUMENTED_ONLY', page)
        self.assertIn('CIO: DOCUMENTED_ONLY', page)
        self.assertIn('работающей реализации не найдено', page)

    def test_a_missing_architect_state_is_UNKNOWN_not_LIVE(self):
        page = _page(architect=None, cio=None)
        self.assertIn('Архитектор: UNKNOWN', page)
        self.assertNotIn('Архитектор: LIVE', page)

    def test_an_unmeasured_work_identity_is_named_not_zeroed(self):
        page = _page()
        studio = page.split('id="view-studio"', 1)[1].split('id="view-build"', 1)[0]
        block = studio.split('уникальных работ доказано', 1)[1].split('</div>', 2)
        self.assertIn('не измерено', ''.join(block[:2]))

    def test_an_intake_channel_that_does_not_exist_says_so(self):
        page = _page()
        self.assertIn('НЕ НАЙДЕНО', page)

    def test_the_bridge_caveat_reaches_the_screen(self):
        """Bridge живой — но «работает ли путь целиком» не измерено, и это видно."""
        self.assertIn('НЕ измерена', _page())


class ThePageIsSelfContained(unittest.TestCase):

    def test_no_network_call_of_any_kind(self):
        page = _page()
        for bad in ('fetch(', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'sendBeacon'):
            self.assertNotIn(bad, page)

    def test_no_external_reference(self):
        page = _page()
        self.assertEqual(re.findall(r'(?:src|href)="(?:https?:)?//', page), [])

    def test_no_service_worker_is_registered(self):
        """Офлайн-кеш приватных данных — утечка с отсрочкой; SW не объявляется."""
        self.assertNotIn('serviceWorker', _page())

    def test_the_contract_refuses_a_smuggled_fetch(self):
        page = _page().replace('</body>', '<script>fetch("/x")</script></body>')
        with self.assertRaises(ws.ShellError) as caught:
            ws.validate_shell(page, 'test')
        self.assertIn('fetch(', str(caught.exception))

    def test_the_contract_refuses_a_service_worker(self):
        page = _page().replace('</body>',
                               '<script>navigator.serviceWorker.register("/sw.js")</script></body>')
        with self.assertRaises(ws.ShellError) as caught:
            ws.validate_shell(page, 'test')
        self.assertIn('service worker', str(caught.exception))

    def test_the_page_forbids_indexing_and_referrers(self):
        page = _page()
        self.assertIn('name="robots" content="noindex,nofollow,noarchive"', page)
        self.assertIn('name="referrer" content="no-referrer"', page)

    def test_a_clean_page_passes_the_contract(self):
        self.assertTrue(ws.validate_shell(_page(), 'test'))


class MobileIsFirstClass(unittest.TestCase):

    def test_the_viewport_covers_the_notch(self):
        self.assertIn('viewport-fit=cover', _page())

    def test_the_bottom_tabs_exist_and_respect_the_safe_area(self):
        page = _page()
        self.assertIn('safe-area-inset-bottom', page)
        self.assertIn('nav{position:fixed', page.replace('\n', ''))

    def test_the_desktop_breakpoint_moves_the_same_three_layers_up(self):
        page = _page()
        self.assertIn('@media (min-width:820px)', page)
        wide = page.split('@media (min-width:820px)', 1)[1]
        self.assertIn('nav{position:sticky', wide.replace('\n', ''))

    def test_apple_home_screen_metadata_is_present(self):
        page = _page()
        for tag in ('apple-mobile-web-app-capable', 'apple-touch-icon',
                    'apple-mobile-web-app-title'):
            self.assertIn(tag, page)

    def test_the_manifest_is_installable_and_declares_no_offline_cache(self):
        m = ws.manifest()
        self.assertEqual(m['display'], 'standalone')
        self.assertTrue(m['icons'])
        self.assertEqual(m['start_url'], './index.html')
        self.assertNotIn('serviceworker', json.dumps(m).lower())


class TheShellShowsItsOwnProvenance(unittest.TestCase):

    def test_the_footer_names_the_projection_digest_and_the_redaction_counts(self):
        p = _projection()
        page = _page(projection=p)
        self.assertIn(p['semantic_digest'], page)
        self.assertIn('не опубликовано как UNKNOWN', page)

    def test_the_page_declares_itself_read_only_and_derived(self):
        page = _page()
        self.assertIn('ТОЛЬКО ЧТЕНИЕ', page)
        self.assertIn('не источник правды', page)

    def test_no_health_score_is_invented(self):
        page = _page()
        self.assertIn('общего балла здоровья нет', page)


if __name__ == '__main__':
    unittest.main()


class TheRealMoneyPolicyIsVisibleToTheOwner(unittest.TestCase):
    """Правило, о котором владелец не прочитал, он не сможет и подтвердить."""

    def test_the_four_real_classes_are_shown_by_name(self):
        page = _page()
        for label in ('Сводная сумма реальных денег',
                      'Разбивка по позициям и протоколам',
                      'Адреса кошельков и номера счетов',
                      'Сырые улики'):
            self.assertIn(label, page)

    def test_identifiers_are_shown_as_NEVER_and_the_rest_as_BLOCKED(self):
        page = _page()
        card = page.split('Реальные деньги', 1)[1].split('</section>', 1)[0]
        row = card.split('Адреса кошельков', 1)[1].split('</tr>', 1)[0]
        self.assertIn('NEVER', row)
        self.assertIn('class="never"', row)
        summary = card.split('Сводная сумма', 1)[1].split('</tr>', 1)[0]
        self.assertIn('BLOCKED', summary)

    def test_the_default_deny_rule_is_stated_in_words_on_the_screen(self):
        page = _page()
        self.assertIn('UNKNOWN → BLOCKED', page)

    def test_the_policy_card_lives_in_CAPITAL_not_elsewhere(self):
        page = _page()
        capital = page.split('id="view-capital"', 1)[1].split('id="view-studio"', 1)[0]
        self.assertIn('Реальные деньги', capital)
        rest = page.split('id="view-studio"', 1)[1]
        self.assertNotIn('Реальные деньги', rest)
