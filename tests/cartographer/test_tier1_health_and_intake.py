"""Контракт здоровья и разбор входящего.

Флагманский случай здоровья: компонент с живым процессом, свежим маячком и нулевым кодом
возврата, который трое суток не делает своего дела. Контракт обязан назвать его больным,
иначе он не нужен.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'cartographer'))

import health_contract as hc        # noqa: E402
import intake_classifier as ic      # noqa: E402

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def sandbox():
    root = Path(tempfile.mkdtemp(prefix='health-'))
    (root / 'data').mkdir()
    return root


def touch(root, rel, *, hours_old=0.0, content='{}'):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')
    import os
    stamp = NOW.timestamp() - hours_old * 3600
    os.utime(p, (stamp, stamp))
    return p


def exit_log(logdir, name, *, agent, code, hours_old=0.0):
    ts = (NOW - timedelta(hours=hours_old)).strftime('%Y-%m-%dT%H:%M:%SZ')
    p = Path(logdir) / name
    p.write_text(f'[{ts}] START agent={agent}\n[{ts}] EXIT agent={agent} code={code}\n',
                 encoding='utf-8')
    return p


class ExistenceIsNotSuccess(unittest.TestCase):
    """Главное утверждение контракта."""

    def test_stale_purpose_signal_is_unhealthy_despite_a_clean_exit(self):
        # Живой замер: маячок свеж, код 0, а файл смещения не двигался 82 часа.
        root = sandbox()
        logs = Path(tempfile.mkdtemp(prefix='logs-'))
        touch(root, 'data/offset.json', hours_old=82.5)
        exit_log(logs, 'spa_bot.log', agent='bot', code=0, hours_old=0.1)
        r = hc.evaluate({'label': 'com.spa.bot', 'tier': 'C1',
                         'success': {'log': 'spa_bot.log', 'agent_name': 'bot',
                                     'ok_values': [0]},
                         'purpose_signal': {'path': 'data/offset.json',
                                            'max_age_hours': 6.0},
                         'output_absence_means': 'FAILURE'},
                        production_root=root, now=NOW, log_root=logs)
        self.assertEqual(r['verdict'], hc.UNHEALTHY)
        self.assertTrue(r['existence_is_not_success'])

    def test_fresh_purpose_signal_is_healthy(self):
        root = sandbox()
        logs = Path(tempfile.mkdtemp(prefix='logs-'))
        touch(root, 'data/offset.json', hours_old=0.5)
        exit_log(logs, 'spa_bot.log', agent='bot', code=0, hours_old=0.6)
        r = hc.evaluate({'label': 'com.spa.bot', 'success': {
            'log': 'spa_bot.log', 'agent_name': 'bot', 'ok_values': [0]},
            'purpose_signal': {'path': 'data/offset.json', 'max_age_hours': 6.0},
            'output_absence_means': 'FAILURE'},
            production_root=root, now=NOW, log_root=logs)
        self.assertEqual(r['verdict'], hc.HEALTHY)


class AbsenceHasFourMeanings(unittest.TestCase):
    def _verdict(self, absence):
        root = sandbox()
        return hc.evaluate({'label': 'com.spa.x', 'success': {},
                            'purpose_signal': {'path': 'data/none.json',
                                               'max_age_hours': 3.0},
                            'output_absence_means': absence},
                           production_root=root, now=NOW,
                           log_root=tempfile.mkdtemp())['verdict']

    def test_absence_as_failure(self):
        self.assertEqual(self._verdict('FAILURE'), hc.UNHEALTHY)

    def test_absence_as_health(self):
        # Реактор угроз: выход — файл ВКЛЮЧЁННОГО стоп-крана. Нет файла — нет аварии.
        self.assertEqual(self._verdict('HEALTHY_WHEN_ABSENT'), hc.HEALTHY)

    def test_absence_as_zero_events(self):
        self.assertEqual(self._verdict('ZERO_EVENTS'), hc.HEALTHY)

    def test_absence_as_unmeasured(self):
        self.assertEqual(self._verdict('NOT_MEASURED'), hc.NOT_MEASURED)

    def test_unknown_absence_meaning_is_refused(self):
        with self.assertRaises(hc.ContractError):
            hc.evaluate({'label': 'x', 'output_absence_means': 'НАВЕРНОЕ_ОК'},
                        production_root=sandbox(), now=NOW)


class ByDesignExitIsNotFailure(unittest.TestCase):
    def test_declared_by_design_code_is_healthy(self):
        # Дневной цикл: код 3 — штатный отказ политики, а не поломка.
        root = sandbox()
        logs = Path(tempfile.mkdtemp())
        exit_log(logs, 'spa_c.log', agent='c', code=3, hours_old=0.1)
        r = hc.evaluate({'label': 'com.spa.c', 'success': {
            'log': 'spa_c.log', 'agent_name': 'c', 'ok_values': [0],
            'by_design_values': [3]}, 'output_absence_means': 'NOT_MEASURED'},
            production_root=root, now=NOW, log_root=logs)
        self.assertEqual(r['verdict'], hc.HEALTHY)
        self.assertIn('штатным', r['checks'][0]['why'])

    def test_undeclared_nonzero_code_is_unhealthy(self):
        root = sandbox()
        logs = Path(tempfile.mkdtemp())
        exit_log(logs, 'spa_c.log', agent='c', code=9, hours_old=0.1)
        r = hc.evaluate({'label': 'com.spa.c', 'success': {
            'log': 'spa_c.log', 'agent_name': 'c', 'ok_values': [0]},
            'output_absence_means': 'NOT_MEASURED'},
            production_root=root, now=NOW, log_root=logs)
        self.assertEqual(r['verdict'], hc.UNHEALTHY)


class StaleExitCodeDoesNotDecide(unittest.TestCase):
    """Ошибка первой редакции: старый код объявил работающий компонент больным."""

    def test_exit_older_than_the_purpose_signal_is_superseded(self):
        root = sandbox()
        logs = Path(tempfile.mkdtemp())
        touch(root, 'data/out.json', hours_old=0.1)          # успех ПОСЛЕ кода
        exit_log(logs, 'spa_b.log', agent='b', code=2, hours_old=9.0)
        r = hc.evaluate({'label': 'com.spa.b', 'success': {
            'log': 'spa_b.log', 'agent_name': 'b', 'ok_values': [0]},
            'purpose_signal': {'path': 'data/out.json', 'max_age_hours': 30.0},
            'output_absence_means': 'FAILURE'},
            production_root=root, now=NOW, log_root=logs)
        exit_check = next(c for c in r['checks'] if c['check'] == 'last_exit')
        self.assertEqual(exit_check['verdict'], hc.NOT_MEASURED)
        self.assertTrue(exit_check['superseded_by_purpose_signal'])
        self.assertEqual(r['verdict'], hc.HEALTHY)

    def test_exit_newer_than_the_purpose_signal_still_decides(self):
        root = sandbox()
        logs = Path(tempfile.mkdtemp())
        touch(root, 'data/out.json', hours_old=9.0)
        exit_log(logs, 'spa_b.log', agent='b', code=2, hours_old=0.1)
        r = hc.evaluate({'label': 'com.spa.b', 'success': {
            'log': 'spa_b.log', 'agent_name': 'b', 'ok_values': [0]},
            'purpose_signal': {'path': 'data/out.json', 'max_age_hours': 30.0},
            'output_absence_means': 'FAILURE'},
            production_root=root, now=NOW, log_root=logs)
        self.assertEqual(r['verdict'], hc.UNHEALTHY)


class BlindValues(unittest.TestCase):
    """Наблюдение есть, доверия нет."""

    def test_fallback_marks_a_fresh_artifact_blind(self):
        root = sandbox()
        touch(root, 'data/flags.json', hours_old=0.1,
              content=json.dumps({'fallback_used': True}))
        r = hc.evaluate({'label': 'com.spa.m', 'success': {},
                         'purpose_signal': {'path': 'data/flags.json',
                                            'max_age_hours': 6.0},
                         'output_absence_means': 'FAILURE',
                         'blind_values': [{'path': 'data/flags.json',
                                           'field': 'fallback_used',
                                           'blind_when': True, 'why': 'запасной источник'}]},
                        production_root=root, now=NOW, log_root=tempfile.mkdtemp())
        self.assertEqual(r['verdict'], hc.BLIND)

    def test_no_fallback_leaves_it_healthy(self):
        root = sandbox()
        touch(root, 'data/flags.json', hours_old=0.1,
              content=json.dumps({'fallback_used': False}))
        r = hc.evaluate({'label': 'com.spa.m', 'success': {},
                         'purpose_signal': {'path': 'data/flags.json',
                                            'max_age_hours': 6.0},
                         'output_absence_means': 'FAILURE',
                         'blind_values': [{'path': 'data/flags.json',
                                           'field': 'fallback_used',
                                           'blind_when': True}]},
                        production_root=root, now=NOW, log_root=tempfile.mkdtemp())
        self.assertEqual(r['verdict'], hc.HEALTHY)

    def test_blind_is_not_counted_as_unhealthy(self):
        self.assertNotEqual(hc.BLIND, hc.UNHEALTHY)


class CoverageHonesty(unittest.TestCase):
    def test_only_declared_entities_get_a_verdict(self):
        m = hc.build_health([], production_root=sandbox(), now=NOW)
        self.assertEqual(m['declared_contracts'], 0)
        self.assertIn('не то же, что', m['coverage_note'])

    def test_contract_without_a_label_is_refused(self):
        with self.assertRaises(hc.ContractError):
            hc.evaluate({'tier': 'C1'}, production_root=sandbox(), now=NOW)

    def test_declared_contracts_file_is_valid(self):
        decl = json.loads((ROOT / 'architecture' / 'health_contracts.json')
                          .read_text(encoding='utf-8'))
        self.assertEqual(decl['schema'], 'health_contracts/1')
        for c in decl['contracts']:
            self.assertIn(c['output_absence_means'], hc.ABSENCE_MEANS)
            self.assertIn(c['tier'], hc.TIERS)
            self.assertTrue(c.get('purpose'), f'{c["label"]} без назначения')
            if c['output_absence_means'] != 'FAILURE':
                self.assertTrue(c.get('absence_basis'),
                                f'{c["label"]}: смысл отсутствия объявлен без основания')


class IntakeClassifier(unittest.TestCase):
    def test_prose_domain_key_is_never_written(self):
        out = ic.classify(fields={'title': 'нечто'}, body='')
        self.assertEqual(out['writes_to_key'], ic.LABEL_KEY)
        self.assertNotEqual(ic.LABEL_KEY, ic.PROSE_KEY)
        self.assertEqual(out['prose_key_untouched'], ic.PROSE_KEY)

    def test_finding_key_survives_quoting(self):
        # Правило со 100 % точностью срабатывало НОЛЬ раз: значение в кавычках.
        out = ic.classify(fields={'title': 'x',
                                  'finding_key': '"B5:drift:com.spa.thing"'}, body='')
        self.assertEqual(out[ic.LABEL_KEY], 'RELIABILITY')
        self.assertEqual(out['confidence'], 'PROVEN')
        self.assertTrue(out['routable'])

    def test_gap_prefix_maps_to_capital(self):
        out = ic.classify(fields={'title': 'x',
                                  'finding_key': '"gap:opportunity_unnamed:aave_v3"'},
                          body='')
        self.assertEqual(out[ic.LABEL_KEY], 'CAPITAL')

    def test_no_signal_is_unknown_not_a_guess(self):
        out = ic.classify(fields={'title': 'просто что-то'}, body='')
        self.assertEqual(out[ic.LABEL_KEY], 'UNKNOWN')
        self.assertEqual(out['confidence'], 'NOT_DERIVABLE')

    def test_heuristic_never_routes(self):
        # Замер: эвристика верна в 6 случаях из 19 и даёт 5 критических ошибок.
        out = ic.classify(fields={'title': 'находка по манифесту флота'}, body='',
                          lexicon={'манифест': 'STUDIO'})
        self.assertEqual(out['confidence'], 'HEURISTIC')
        self.assertFalse(out['routable'])
        self.assertEqual(out['routed_domain'], 'UNKNOWN')
        self.assertEqual(out['suggestion'], 'STUDIO')

    def test_equal_cost_contest_refuses_to_guess(self):
        out = ic.classify(fields={'title': 'утечка секрета в money-path'},
                          body='spa_core/risk/policy.py\nspa_core/risk/gate.py')
        self.assertIn(out[ic.LABEL_KEY], ('UNKNOWN',))
        self.assertEqual(out['confidence'], 'CONTESTED')
        self.assertTrue(len(out['contested_domains']) >= 2)

    def test_classifier_never_authorizes_execution(self):
        for fields in ({'title': 'x'}, {'title': 'y', 'finding_key': '"B1:dead:z"'}):
            self.assertFalse(ic.classify(fields=fields, body='')['authorizes_execution'])

    def test_rejected_signals_are_named_with_their_measurement(self):
        for name, why in ic.REJECTED_SIGNALS.items():
            self.assertRegex(why, r'\d', f'{name}: отказ без измерения')

    def test_security_marker_in_body_alone_is_not_enough(self):
        # Первая редакция ловила одно упоминание и объявляла безопасностью карточки
        # про капитал.
        out = ic.classify(fields={'title': 'доходность протокола'},
                          body='в примечании упомянут секрет')
        self.assertNotEqual(out[ic.LABEL_KEY], 'SECURITY')

    def test_security_marker_in_title_is_enough(self):
        out = ic.classify(fields={'title': 'утечка токена в логах'}, body='')
        self.assertEqual(out[ic.LABEL_KEY], 'SECURITY')

    def test_lexicon_keeps_only_discriminating_words(self):
        labelled = [{'title': 'манифест флота дрейф', 'domain': 'RELIABILITY'},
                    {'title': 'манифест флота парность', 'domain': 'RELIABILITY'},
                    {'title': 'доходность манифест', 'domain': 'CAPITAL'}]
        lex = ic.build_lexicon(labelled, min_occurrences=2)
        self.assertNotIn('манифест', lex, 'слово, общее двум предметам, не различает')
        self.assertEqual(lex.get('флота'), 'RELIABILITY')

    def test_glob_path_is_not_a_subject(self):
        out = ic.classify(fields={'title': 'нечто'}, body='landing/**')
        self.assertEqual(out[ic.LABEL_KEY], 'UNKNOWN')

    def test_concrete_landing_path_is_product(self):
        out = ic.classify(fields={'title': 'нечто'}, body='landing/src/pages/index.astro')
        self.assertEqual(out[ic.LABEL_KEY], 'PRODUCT')


if __name__ == '__main__':
    unittest.main()


class SixStatesNotOneScore(unittest.TestCase):
    """Шесть состояний отвечают на разные вопросы. Единого числа здоровья нет."""

    def test_vocabulary_has_all_six(self):
        for v in ('HEALTHY', 'UNHEALTHY', 'DEGRADED', 'BLIND', 'NOT_MEASURED',
                  'NOT_APPLICABLE'):
            self.assertIn(v, hc.VERDICTS)

    def test_no_synthetic_score_is_declared(self):
        m = hc.build_health([], production_root=sandbox(), now=NOW)
        self.assertTrue(m['no_synthetic_score'])

    def test_degraded_sits_between_healthy_and_unhealthy(self):
        root = sandbox()
        touch(root, 'data/out.json', hours_old=5.0)
        r = hc.evaluate({'label': 'com.spa.x', 'success': {},
                         'purpose_signal': {'path': 'data/out.json',
                                            'warn_age_hours': 3.0,
                                            'max_age_hours': 8.0},
                         'output_absence_means': 'FAILURE'},
                        production_root=root, now=NOW, log_root=tempfile.mkdtemp())
        self.assertEqual(r['verdict'], hc.DEGRADED)

    def test_fresher_than_warning_is_healthy(self):
        root = sandbox()
        touch(root, 'data/out.json', hours_old=1.0)
        r = hc.evaluate({'label': 'com.spa.x', 'success': {},
                         'purpose_signal': {'path': 'data/out.json',
                                            'warn_age_hours': 3.0,
                                            'max_age_hours': 8.0},
                         'output_absence_means': 'FAILURE'},
                        production_root=root, now=NOW, log_root=tempfile.mkdtemp())
        self.assertEqual(r['verdict'], hc.HEALTHY)

    def test_scheduled_liveness_is_not_applicable(self):
        root = sandbox()
        touch(root, 'data/out.json', hours_old=1.0)
        r = hc.evaluate({'label': 'com.spa.x', 'success': {},
                         'purpose_signal': {'path': 'data/out.json',
                                            'max_age_hours': 8.0},
                         'liveness': {'expected': 'SCHEDULED'},
                         'output_absence_means': 'FAILURE'},
                        production_root=root, now=NOW, log_root=tempfile.mkdtemp())
        live = next(c for c in r['checks'] if c['check'] == 'liveness')
        self.assertEqual(live['verdict'], hc.NOT_APPLICABLE)
        # НЕПРИМЕНИМО не влияет на свод: это ответ «вопрос не тот», а не оценка.
        self.assertEqual(r['verdict'], hc.HEALTHY)

    def test_daemon_without_a_process_is_unhealthy(self):
        root = sandbox()
        touch(root, 'data/out.json', hours_old=1.0)
        r = hc.evaluate({'label': 'com.spa.x', 'success': {},
                         'purpose_signal': {'path': 'data/out.json',
                                            'max_age_hours': 8.0},
                         'liveness': {'expected': 'DAEMON', 'has_pid': False},
                         'output_absence_means': 'FAILURE'},
                        production_root=root, now=NOW, log_root=tempfile.mkdtemp())
        self.assertEqual(r['verdict'], hc.UNHEALTHY)

    def test_unsupplied_pid_is_not_measured_not_false(self):
        root = sandbox()
        touch(root, 'data/out.json', hours_old=1.0)
        r = hc.evaluate({'label': 'com.spa.x', 'success': {},
                         'purpose_signal': {'path': 'data/out.json',
                                            'max_age_hours': 8.0},
                         'liveness': {'expected': 'DAEMON'},
                         'output_absence_means': 'FAILURE'},
                        production_root=root, now=NOW, log_root=tempfile.mkdtemp())
        live = next(c for c in r['checks'] if c['check'] == 'liveness')
        self.assertEqual(live['verdict'], hc.NOT_MEASURED)


class ExistenceOnlyContractIsRefused(unittest.TestCase):
    """Контракт, проверяющий только существование, — не контракт.

    Первая редакция продуктового набора содержала такой: координатор моста получил
    HEALTHY по одному наличию процесса, а его артефакт не двигался четверо суток.
    """

    def test_failure_absence_without_a_purpose_signal_is_refused(self):
        with self.assertRaises(hc.ContractError):
            hc.evaluate({'label': 'com.spa.x', 'output_absence_means': 'FAILURE',
                         'success': {}}, production_root=sandbox(), now=NOW)

    def test_declaring_a_purpose_signal_makes_it_acceptable(self):
        root = sandbox()
        touch(root, 'data/out.json', hours_old=1.0)
        r = hc.evaluate({'label': 'com.spa.x', 'output_absence_means': 'FAILURE',
                         'success': {},
                         'purpose_signal': {'path': 'data/out.json',
                                            'max_age_hours': 8.0}},
                        production_root=root, now=NOW, log_root=tempfile.mkdtemp())
        self.assertEqual(r['verdict'], hc.HEALTHY)

    def test_external_root_is_declared_not_guessed(self):
        outside = Path(tempfile.mkdtemp(prefix='outside-'))
        (outside / 'state').mkdir()
        f = outside / 'state' / 'x.json'
        f.write_text('{}', encoding='utf-8')
        import os
        os.utime(f, (NOW.timestamp() - 3600, NOW.timestamp() - 3600))
        r = hc.evaluate({'label': 'com.other.x', 'success': {},
                         'purpose_signal': {'root': str(outside),
                                            'path': 'state/x.json',
                                            'max_age_hours': 8.0},
                         'output_absence_means': 'FAILURE'},
                        production_root=sandbox(), now=NOW, log_root=tempfile.mkdtemp())
        self.assertEqual(r['verdict'], hc.HEALTHY)

    def test_production_contract_set_declares_a_purpose_signal_where_required(self):
        decl = json.loads((ROOT / 'architecture' / 'health_contracts.json')
                          .read_text(encoding='utf-8'))
        for c in decl['contracts']:
            if c['output_absence_means'] == 'FAILURE':
                self.assertTrue((c.get('purpose_signal') or {}).get('path'),
                                f'{c["label"]}: провал объявлен без признака назначения')
