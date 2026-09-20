"""Тесты web-safe проекции Director OS (v1.1 Epic 1).

Каждый тест ниже — либо реальная находка аудита 20.09, либо положительный контроль на неё.
Проверка, никогда не видевшая настоящей утечки, — украшение (`.claude/rules/deployment.md`).

Замеры аудита, которые здесь воспроизводятся:
  · 704 абсолютных пути с именем пользователя на work.html;
  · 3 483 метки launchd на reliability.html;
  · два ИМЕНИ секретов в тексте карточек;
  · REAL-капитал не доказан ни одним источником.
"""
import json
import sys
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cartographer import web_projection as wp  # noqa: E402


def _investments(**kw):
    base = {
        'real_capital_proven': False,
        'real_capital_note': 'ни один источник не объявил режим REAL поимённо',
        'mode_vocabulary': ['REAL', 'PAPER', 'SHADOW', 'FORECAST', 'RND', 'UNKNOWN'],
        'metric_vocabulary': ['CONFIGURED_CAPITAL', 'CURRENT_EQUITY', 'NET_PNL'],
        'capital_by_mode': {'REAL': None, 'PAPER': 101340.69, 'SHADOW': None},
        'capital_metrics': [{'metric_type': 'CURRENT_EQUITY', 'mode': 'PAPER',
                             'value': 101340.69, 'currency': 'USDC',
                             'source': '/Users/someone/Documents/SPA_Claude/data/equity.json'}],
        'kill_switch': {'status': 'READ', 'triggered': False, 'reason': 'all clear'},
        'golive': {'ready': True, 'passed': 29, 'total': 29},
        'rnd_stage_counts': {'BACKTEST_PASS': 0, 'PAPER_CANDIDATE': 4, 'REJECT': 6},
        'counts': {'objects': 81, 'by_mode': {'PAPER': 70, 'RND': 11}},
        'objects': [],
        'limits': ['капитал режима REAL не доказан'],
    }
    base.update(kw)
    return base


def _actions(**kw):
    base = {
        'counts': {'candidates': 5, 'ready_for_ui': 0, 'not_ready': 5, 'red_zone': 13},
        'red_zone': ['move_capital', 'execute_trade'],
        'required_properties': ['canonical_executor', 'audit_record', 'rollback'],
        'ui_exposes_actions': False,
        'actions': [{'action': 'rebuild_portal', 'verdict': 'NOT_READY_FOR_UI',
                     'destructive': False, 'missing_properties': ['audit_record'],
                     'canonical_executor': 'scripts/cartographer/portal.py'}],
    }
    base.update(kw)
    return base


class TheProjectionRefusesToCarrySensitiveShapes(unittest.TestCase):
    """Положительные контроли: каждая форма из аудита обязана не доехать."""

    def test_an_absolute_home_path_becomes_repo_relative(self):
        text = '/Users/testowner/Documents/SPA_Claude/nimbalyst-local/tracker/x.md'
        out = wp.redact_text(text)
        self.assertEqual(out, 'nimbalyst-local/tracker/x.md')
        self.assertNotIn('/Users/', out)
        self.assertNotIn('testowner', out)

    def test_a_path_outside_production_is_named_not_shortened(self):
        """Путь вне прод-дерева нельзя сделать repo-relative — его надо НАЗВАТЬ."""
        out = wp.redact_text('/Users/someone/studio-os-snapshots/phase9/pages/index.html')
        self.assertEqual(out, '[ПУТЬ ВНЕ ПРОД-ДЕРЕВА]')

    def test_a_tilde_path_is_caught_too(self):
        self.assertEqual(wp.redact_text('лежит в ~/studio-os-snapshots/x'),
                         'лежит в [ПУТЬ ВНЕ ПРОД-ДЕРЕВА]')

    def test_a_launchd_label_becomes_a_service_name(self):
        """Переименование, а не сокрытие: имя службы остаётся читаемым."""
        self.assertEqual(wp.redact_text('агент com.spa.site_freshness мёртв'),
                         'агент site_freshness мёртв')

    def test_a_bridge_label_is_renamed_by_the_same_rule(self):
        self.assertEqual(wp.redact_text('com.studiobridge.coordinator жив'),
                         'coordinator жив')

    def test_an_internal_address_is_replaced(self):
        for text in ('http://127.0.0.1:8765/api', 'слушает localhost', 'bind 0.0.0.0'):
            self.assertNotIn('127.0.0.1', wp.redact_text(text))
            self.assertNotIn('localhost', wp.redact_text(text))

    def test_a_bare_internal_port_is_replaced(self):
        self.assertIn('[ПОРТ]', wp.redact_text('consumes Family Fund API :8766'))

    def test_a_secret_name_is_cut_even_though_a_name_is_not_a_secret(self):
        """Имя не секрет, но оно называет, ЧТО искать — в веб не уходит."""
        for name in ('TELEGRAM_BOT_TOKEN_SPA', 'SIWE_SESSION_SECRET',
                     'GITHUB_PAT_SPA', 'ETHERSCAN_API_KEY'):
            self.assertNotIn(name, wp.redact_text(f'нужен {name} на сервере'))

    def test_a_pid_is_cut(self):
        self.assertNotIn('98535', wp.redact_text('держатель pid 98535 мёртв'))

    def test_a_field_whose_VALUE_looks_like_a_secret_is_not_published_at_all(self):
        """Редактировать значение секрета нельзя — поле выбрасывается целиком."""
        stats = {}
        policy = wp.Policy(safe=('note',))
        keep, _ = wp.project_value('токен ghp_' + 'A' * 36, policy, 'note', stats)
        self.assertFalse(keep)
        self.assertEqual(stats.get('LOCAL_ONLY'), 1)


class TheDefaultIsNotToPublish(unittest.TestCase):

    def test_a_key_without_a_declared_policy_is_blocked(self):
        stats = {}
        policy = wp.Policy(safe=('known',))
        keep, _ = wp.project_value('что угодно', policy, 'brand_new_field', stats)
        self.assertFalse(keep)
        self.assertEqual(stats.get('UNKNOWN'), 1)
        self.assertIn('brand_new_field', stats['unknown_keys'])

    def test_the_verdict_for_an_undeclared_key_is_literally_UNKNOWN(self):
        self.assertEqual(wp.Policy().verdict('anything'), 'UNKNOWN')

    def test_a_new_snapshot_field_cannot_reach_the_web_silently(self):
        """Авария, против которой написан класс: снимок вырос, а политика не заметила."""
        inv = _investments(sudden_new_field='/Users/testowner/secret/place')
        projection = wp.build_projection(investments=inv, actions=_actions())
        payload = json.dumps(projection, ensure_ascii=False)
        self.assertNotIn('sudden_new_field', payload)
        self.assertNotIn('testowner', payload)


class TheContractRefusesABadProjection(unittest.TestCase):

    def _good(self):
        return wp.build_projection(investments=_investments(), actions=_actions())

    def test_a_clean_projection_passes(self):
        self.assertTrue(wp.validate_projection(self._good(), 'test'))

    def test_a_leftover_absolute_path_is_refused(self):
        p = self._good()
        p['layers']['CAPITAL']['smuggled'] = '/Users/testowner/Documents/x'
        with self.assertRaises(wp.WebProjectionError) as caught:
            wp.validate_projection(p, 'test')
        self.assertIn('абсолютный путь', str(caught.exception))

    def test_a_leftover_launchd_label_is_refused(self):
        p = self._good()
        p['layers']['STUDIO']['smuggled'] = 'com.spa.orchestrator'
        with self.assertRaises(wp.WebProjectionError):
            wp.validate_projection(p, 'test')

    def test_a_leftover_secret_name_is_refused(self):
        p = self._good()
        p['layers']['BUILD']['smuggled'] = 'нужен GITHUB_PAT_SPA'
        with self.assertRaises(wp.WebProjectionError) as caught:
            wp.validate_projection(p, 'test')
        self.assertIn('имя секрета', str(caught.exception))

    def test_a_leftover_secret_VALUE_is_refused(self):
        p = self._good()
        p['layers']['BUILD']['smuggled'] = 'ghp_' + 'B' * 36
        with self.assertRaises(wp.WebProjectionError) as caught:
            wp.validate_projection(p, 'test')
        self.assertIn('ФОРМА секрета', str(caught.exception))

    def test_a_leftover_internal_address_is_refused(self):
        p = self._good()
        p['layers']['STUDIO']['smuggled'] = 'http://127.0.0.1:8765'
        with self.assertRaises(wp.WebProjectionError):
            wp.validate_projection(p, 'test')

    def test_three_layers_exactly_are_required(self):
        p = self._good()
        del p['layers']['BUILD']
        with self.assertRaises(wp.WebProjectionError) as caught:
            wp.validate_projection(p, 'test')
        self.assertIn('ровно три', str(caught.exception))

    def test_a_fourth_layer_is_refused_too(self):
        """Слои — граница навигации владельца, а не свободный список."""
        p = self._good()
        p['layers']['MISC'] = {}
        with self.assertRaises(wp.WebProjectionError):
            wp.validate_projection(p, 'test')

    def test_actions_enabled_true_is_refused_in_epic_1(self):
        p = self._good()
        p['layers']['BUILD']['actions_enabled'] = True
        with self.assertRaises(wp.WebProjectionError) as caught:
            wp.validate_projection(p, 'test')
        self.assertIn('read-only', str(caught.exception).lower())

    def test_the_projection_must_declare_it_is_not_a_source_of_truth(self):
        p = self._good()
        del p['is_not_a_source_of_truth']
        with self.assertRaises(wp.WebProjectionError):
            wp.validate_projection(p, 'test')


class RealCapitalIsNeverInvented(unittest.TestCase):

    def test_unproven_real_capital_is_stated_in_words(self):
        p = wp.build_projection(investments=_investments(), actions=_actions())
        self.assertEqual(p['layers']['CAPITAL']['real_capital_headline'],
                         'REAL CAPITAL: NOT PROVEN')

    def test_a_null_REAL_mode_stays_null_and_is_not_read_as_zero(self):
        """Инвариант #17: «не измерено» ≠ 0. Ноль означал бы «капитала нет»."""
        p = wp.build_projection(investments=_investments(), actions=_actions())
        by_mode = p['layers']['CAPITAL']['capital_by_mode']
        self.assertIsNone(by_mode['REAL'])
        self.assertNotEqual(by_mode['REAL'], 0)
        self.assertEqual(by_mode['PAPER'], 101340.69)

    def test_a_proven_real_capital_removes_the_headline(self):
        """Обратный контроль: при доказанном REAL надпись обязана исчезнуть."""
        p = wp.build_projection(investments=_investments(real_capital_proven=True),
                                actions=_actions())
        self.assertNotIn('real_capital_headline', p['layers']['CAPITAL'])

    def test_an_absent_investment_snapshot_is_a_distinct_state(self):
        p = wp.build_projection(investments=None, actions=_actions())
        self.assertEqual(p['layers']['CAPITAL']['state'], 'NOT_READ')
        self.assertIn('НЕ значит', p['layers']['CAPITAL']['note'])


class CountMapsSurviveThePolicy(unittest.TestCase):
    """Находка разработки: у счётчика ключи — слова вокабуляра, а не имена полей."""

    def test_a_count_map_is_published_whole(self):
        stats = {}
        policy = wp.Policy(count_maps=('by_mode',))
        keep, out = wp.project_value({'PAPER': 70, 'RND': 11}, policy, 'by_mode', stats)
        self.assertTrue(keep)
        self.assertEqual(out, {'PAPER': 70, 'RND': 11})

    def test_without_the_count_map_declaration_the_whole_counter_is_lost(self):
        """Тот самый изъян: обход как записи блокирует каждый термин вокабуляра."""
        stats = {}
        policy = wp.Policy(safe=('by_mode',))
        _keep, out = wp.project_value({'PAPER': 70, 'RND': 11}, policy, 'by_mode', stats)
        self.assertEqual(out, {})
        self.assertEqual(stats.get('UNKNOWN'), 2)

    def test_a_string_inside_a_count_map_is_still_redacted(self):
        stats = {}
        policy = wp.Policy(count_maps=('by_thing',))
        _keep, out = wp.project_value(
            {'label': 'com.spa.orchestrator'}, policy, 'by_thing', stats)
        self.assertEqual(out['label'], 'orchestrator')

    def test_a_secret_value_inside_a_count_map_is_dropped(self):
        stats = {}
        policy = wp.Policy(count_maps=('by_thing',))
        _keep, out = wp.project_value(
            {'tok': 'ghp_' + 'C' * 36, 'n': 3}, policy, 'by_thing', stats)
        self.assertNotIn('tok', out)
        self.assertEqual(out['n'], 3)


class TheProjectionIsRebuildableAndDeclaresItself(unittest.TestCase):

    def test_the_digest_ignores_the_clock(self):
        a = wp.build_projection(investments=_investments(), actions=_actions())
        b = wp.build_projection(investments=_investments(), actions=_actions())
        self.assertNotEqual(a['generated_at'], b['generated_at']) if a['generated_at'] != b['generated_at'] else None
        self.assertEqual(a['semantic_digest'], b['semantic_digest'])

    def test_a_real_change_DOES_move_the_digest(self):
        """Обратный контроль: дайджест, который не двигается, ничего не охраняет."""
        a = wp.build_projection(investments=_investments(), actions=_actions())
        b = wp.build_projection(
            investments=_investments(capital_by_mode={'REAL': None, 'PAPER': 999.0}),
            actions=_actions())
        self.assertNotEqual(a['semantic_digest'], b['semantic_digest'])

    def test_the_projection_declares_its_four_classes(self):
        p = wp.build_projection(investments=_investments(), actions=_actions())
        self.assertEqual(tuple(p['classification_vocabulary']), wp.CLASSES)
        for name in wp.CLASSES:
            self.assertIn(name, p['classification_definitions'])

    def test_the_stats_account_for_every_decision(self):
        p = wp.build_projection(investments=_investments(), actions=_actions())
        stats = p['redaction_stats']
        self.assertEqual(set(stats), {'SAFE_FOR_PRIVATE_WEB', 'REDACTED',
                                      'LOCAL_ONLY', 'UNKNOWN_BLOCKED'})
        self.assertGreater(stats['SAFE_FOR_PRIVATE_WEB'], 0)

    def test_the_launchd_note_does_not_itself_contain_a_label(self):
        """Настоящая находка сборки: пояснение политики нарушало свою же политику."""
        p = wp.build_projection(investments=_investments(), actions=_actions())
        self.assertIsNone(wp._LAUNCHD_LABEL.search(p['launchd_label_note']))


class NothingIsExecutedAndNothingLeaves(unittest.TestCase):

    def test_the_module_imports_no_network_and_no_subprocess(self):
        import ast
        tree = ast.parse((ROOT / 'scripts/cartographer/web_projection.py').read_text())
        banned = {'socket', 'urllib', 'http', 'requests', 'subprocess', 'asyncio'}
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append(node.module.split('.')[0])
        self.assertEqual(sorted(set(found) & banned), [])

    def test_the_output_may_not_land_in_production_or_behind_a_symlink(self):
        import tempfile
        from scripts.cartographer import diff as diff_mod
        with tempfile.TemporaryDirectory() as tmp:
            protected = Path(tmp) / 'bundle'
            protected.mkdir()
            with self.assertRaises(Exception):
                diff_mod.validate_output(protected / 'inside', [protected])

    def test_the_build_layer_never_reports_an_enabled_action(self):
        p = wp.build_projection(investments=_investments(),
                                actions=_actions(counts={'ready_for_ui': 7}))
        self.assertFalse(p['layers']['BUILD']['actions_enabled'])


if __name__ == '__main__':
    unittest.main()


class RealMoneyCannotExpandExposureSilently(unittest.TestCase):
    """Правило ARB 20.09, написанное НА БУДУЩЕЕ.

    Сегодня режим REAL не доказан ни одним источником. Именно поэтому класс и опасен:
    когда источник дорастёт, поле поедет в веб без единой правки политики. Каждый тест
    ниже — будущая авария, воспроизведённая заранее.
    """

    def _real_object(self, **kw):
        base = {'mode': 'REAL', 'freshness': 'FRESH', 'observed_at': '2026-10-01T00:00:00Z',
                'capital_value': 250000.0, 'positions': [{'protocol': 'aave', 'usd': 100000}],
                'wallet_address': '0x' + 'a' * 40,
                'tx_hash': 'b' * 64, 'strategy_name': 'live_yield'}
        base.update(kw)
        return base

    def test_a_future_REAL_record_publishes_no_numbers_at_all(self):
        p = wp.build_projection(investments=_investments(objects=[self._real_object()]),
                                actions=_actions())
        strat = p['layers']['CAPITAL']['strategies'][0]
        self.assertEqual(strat['mode'], 'REAL')
        self.assertNotIn('capital_value', strat)
        self.assertNotIn('positions', strat)
        self.assertNotIn('wallet_address', strat)
        self.assertNotIn('tx_hash', strat)

    def test_the_owner_is_told_the_data_exists_but_is_closed(self):
        """«Закрыто» и «данных нет» — разные ответы; второй был бы ложью."""
        p = wp.build_projection(investments=_investments(objects=[self._real_object()]),
                                actions=_actions())
        strat = p['layers']['CAPITAL']['strategies'][0]
        self.assertIn('blocked_classes', strat)
        self.assertIn('WALLET_ACCOUNT_IDENTIFIER', strat['blocked_classes'])
        self.assertIn('REAL_CAPITAL_SUMMARY', strat['blocked_classes'])
        self.assertIn('одобрения владельцем', strat['blocked_reason'])

    def test_an_UNCLASSIFIED_new_real_field_is_blocked_by_default(self):
        """Умолчание UNKNOWN → BLOCKED: поле, которого политика не знает, не уходит.

        Проверка идёт по КЛЮЧУ и по значению как числу, а не подстрокой по всему JSON:
        первая редакция искала «42» в дампе целиком и падала, когда цифры попадали в
        `generated_at` — бомба на часах, ровно тот класс, что описан в правилах доставки.
        """
        marker = 987654.321          # значение, которого нет ни в одном счётчике фикстуры
        p = wp.build_projection(
            investments=_investments(
                objects=[self._real_object(brand_new_real_metric=marker)]),
            actions=_actions())
        strat = p['layers']['CAPITAL']['strategies'][0]
        self.assertNotIn('brand_new_real_metric', strat)
        self.assertIn('UNCLASSIFIED_REAL_FIELD', strat['blocked_classes'])
        payload = json.dumps({k: v for k, v in p.items()
                              if k not in ('generated_at', 'semantic_digest')},
                             ensure_ascii=False)
        self.assertNotIn(repr(marker), payload)
        self.assertNotIn('987654', payload)

    def test_a_PAPER_record_is_unaffected_by_the_real_policy(self):
        """Принятое поведение PAPER не должно измениться ни на байт."""
        paper = {'mode': 'PAPER', 'capital_value': 100.0, 'title': 'бумажная',
                 'lifecycle_state': 'ACTIVE'}
        p = wp.build_projection(investments=_investments(objects=[paper]),
                                actions=_actions())
        strat = p['layers']['CAPITAL']['strategies'][0]
        self.assertEqual(strat['capital_value'], 100.0)
        self.assertNotIn('blocked_classes', strat)

    def test_the_verdict_for_an_unknown_real_class_is_BLOCKED(self):
        verdict, cls = wp.real_verdict('some_field_nobody_declared')
        self.assertEqual(verdict, 'BLOCKED')
        self.assertIsNone(cls)

    def test_identifiers_are_NEVER_not_merely_BLOCKED(self):
        """NEVER — граница, а не настройка: её нельзя снять одобрением."""
        self.assertEqual(wp.REAL_WEB_POLICY['WALLET_ACCOUNT_IDENTIFIER'], 'NEVER')
        for cls in ('REAL_CAPITAL_SUMMARY', 'REAL_POSITION_DETAIL',
                    'RAW_INVESTMENT_EVIDENCE'):
            self.assertEqual(wp.REAL_WEB_POLICY[cls], 'BLOCKED')

    def test_a_wallet_shape_is_cut_from_any_text_regardless_of_the_field(self):
        """Ярлык режима переставить легко — форма адреса от этого не меняется."""
        for addr in ('0x' + 'C' * 40, 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4'):
            self.assertNotIn(addr, wp.redact_text(f'кошелёк {addr} пополнен'))

    def test_an_iban_shape_is_cut_too(self):
        self.assertNotIn('DE89370400440532013000',
                         wp.redact_text('счёт DE89370400440532013000'))

    def test_a_field_carrying_a_wallet_is_dropped_not_redacted(self):
        """Идентификатор счёта не «чистят» — поле выбрасывают целиком."""
        self.assertEqual(wp.classify_text('0x' + 'd' * 40), 'LOCAL_ONLY')

    def test_the_contract_refuses_a_leftover_wallet_anywhere(self):
        p = wp.build_projection(investments=_investments(), actions=_actions())
        p['layers']['STUDIO']['smuggled'] = 'перевод на 0x' + 'e' * 40
        with self.assertRaises(wp.WebProjectionError) as caught:
            wp.validate_projection(p, 'test')
        self.assertIn('НИКОГДА', str(caught.exception))

    def test_the_projection_declares_the_real_policy_in_the_artifact(self):
        """Контракт, о котором нельзя прочитать в артефакте, снаружи нечем проверить."""
        p = wp.build_projection(investments=_investments(), actions=_actions())
        capital = p['layers']['CAPITAL']
        self.assertEqual(capital['real_web_policy'], wp.REAL_WEB_POLICY)
        self.assertEqual(tuple(capital['real_class_vocabulary']), wp.REAL_CLASSES)
        self.assertIn('UNKNOWN → BLOCKED', capital['real_policy_note'])

    def test_the_contract_refuses_a_policy_that_disagrees_with_the_module(self):
        """Подмена политики в артефакте ловится равенством — раньше проверки NEVER."""
        p = wp.build_projection(investments=_investments(), actions=_actions())
        p['layers']['CAPITAL']['real_web_policy']['WALLET_ACCOUNT_IDENTIFIER'] = 'BLOCKED'
        with self.assertRaises(wp.WebProjectionError) as caught:
            wp.validate_projection(p, 'test')
        self.assertIn('дословно', str(caught.exception))

    def test_the_NEVER_branch_is_reachable_and_guards_the_module_constant(self):
        """Ветка про NEVER достижима только при ослаблении САМОЙ константы.

        Без этого контроля она была бы украшением: равенство политики отказывает
        раньше, и ветка никогда бы не сработала. Здесь ослабляется константа модуля —
        то есть воспроизводится правка, которую правило и должно поймать.
        """
        with unittest.mock.patch.dict(
                wp.REAL_WEB_POLICY, {'WALLET_ACCOUNT_IDENTIFIER': 'BLOCKED'}):
            p = wp.build_projection(investments=_investments(), actions=_actions())
            with self.assertRaises(wp.WebProjectionError) as caught:
                wp.validate_projection(p, 'test')
            self.assertIn('NEVER', str(caught.exception))
