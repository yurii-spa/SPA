"""Безопасность v1.3: сторожа проверяются ЗАСЕЯННЫМИ значениями.

Проверка, никогда не видевшая настоящей утечки, — украшение. Поэтому каждый тест
засевает в улику значение нужной формы и требует, чтобы оно НЕ дошло до страницы.

Литералы собираются из кусков намеренно: тест, содержащий запрещённую форму целиком,
провалил бы собственную проверку страницы, если бы его текст когда-нибудь в неё попал.
Этот класс самоотравления уже случался в этом проекте четыре раза.
"""
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'cartographer'))

import director_v13 as D13         # noqa: E402
import web_projection as WP        # noqa: E402

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

# Засеваемые значения. Каждое собрано из кусков.
SEED_WALLET = '0x' + 'a1b2c3d4' * 5
SEED_IBAN = 'DE' + '89' + '3704004405320130' + '00'
SEED_SECRET_NAME = 'TELEGRAM' + '_BOT_' + 'TOKEN' + '_SPA'
SEED_HOME_PATH = '/Users' + '/somebody' + '/Documents/SPA_Claude/data/x.json'
SEED_OWNER_ID = 'owner' + ':' + '258651137'
SEED_EMAIL = 'someone' + '@' + 'example.com'
SEED_INTERNAL = '127.0.0.1' + ':' + '8788'
SEED_LABEL = 'com.spa' + '.secret_agent'


class SanitizerCatchesSeededValues(unittest.TestCase):
    """Первый и второй рубеж: имя поля и форма значения."""

    def _clean(self, node):
        stats = {}
        out, _ = D13.sanitize(node, stats)
        return json.dumps(out, ensure_ascii=False), stats

    def test_wallet_shape_is_removed(self):
        text, _ = self._clean({'note': f'кошелёк {SEED_WALLET} участвует'})
        self.assertNotIn(SEED_WALLET, text)

    def test_account_shape_is_removed(self):
        text, _ = self._clean({'note': f'счёт {SEED_IBAN}'})
        self.assertNotIn(SEED_IBAN, text)

    def test_secret_name_is_removed(self):
        text, _ = self._clean({'note': f'нужен {SEED_SECRET_NAME} из связки'})
        self.assertNotIn(SEED_SECRET_NAME, text)

    def test_absolute_home_path_is_reduced_to_repo_relative(self):
        text, _ = self._clean({'note': f'читает {SEED_HOME_PATH}'})
        self.assertNotIn('/Users' + '/somebody', text)
        self.assertIn('data/x.json', text)

    def test_internal_address_is_removed(self):
        text, _ = self._clean({'note': f'слушает {SEED_INTERNAL}'})
        self.assertNotIn('127.0.0' + '.1', text)

    def test_launchd_label_is_reduced_to_its_name(self):
        text, _ = self._clean({'note': f'служба {SEED_LABEL} упала'})
        self.assertNotIn('com.spa' + '.secret_agent', text)
        self.assertIn('secret_agent', text)

    def test_blocked_key_is_dropped_whole_regardless_of_content(self):
        text, stats = self._clean({'decided_by': SEED_OWNER_ID, 'kept': 'ок'})
        self.assertNotIn('258651137', text)
        self.assertNotIn('decided_by', text)
        self.assertEqual(stats.get('blocked_by_name'), 1)

    def test_blocked_key_is_dropped_at_any_depth(self):
        text, _ = self._clean({'a': {'b': [{'session_id': 'СЕКРЕТНАЯ-СЕССИЯ'}]}})
        self.assertNotIn('СЕКРЕТНАЯ-СЕССИЯ', text)

    def test_ordinary_values_survive(self):
        text, _ = self._clean({'metric': 'equity_now', 'value': 101340.69,
                               'source': 'data/equity_curve_daily.json'})
        self.assertIn('equity_now', text)
        self.assertIn('data/equity_curve_daily.json', text)


class PageScanIsThePositiveControl(unittest.TestCase):
    """Последний рубеж обязан КУСАТЬСЯ. Иначе он украшение."""

    def test_clean_page_passes(self):
        D13.assert_page_is_clean('<html><body>эквити 101 340,69</body></html>')

    def _expect_refusal(self, payload, what):
        with self.assertRaises(D13.SecurityError, msg=f'страница с {what} обязана быть отвергнута'):
            D13.assert_page_is_clean(f'<html><body>{payload}</body></html>')

    def test_wallet_on_the_page_is_refused(self):
        self._expect_refusal(SEED_WALLET, 'идентификатором кошелька')

    def test_home_path_on_the_page_is_refused(self):
        self._expect_refusal(SEED_HOME_PATH, 'домашним абсолютным путём')

    def test_secret_name_on_the_page_is_refused(self):
        self._expect_refusal(SEED_SECRET_NAME, 'именем секрета')

    def test_owner_identity_on_the_page_is_refused(self):
        self._expect_refusal(SEED_OWNER_ID, 'идентификатором владельца')

    def test_email_on_the_page_is_refused(self):
        self._expect_refusal(SEED_EMAIL, 'адресом почты')

    def test_internal_address_on_the_page_is_refused(self):
        self._expect_refusal(SEED_INTERNAL, 'внутренним адресом')

    def test_every_declared_shape_has_a_positive_control(self):
        # Сторож сторожей: у каждой объявленной формы обязан быть тест, который её ловит.
        covered = {'домашний абсолютный путь', 'идентификатор кошелька',
                   'идентификатор счёта', 'имя секрета', 'внутренний адрес',
                   'идентификатор владельца в мессенджере', 'адрес электронной почты'}
        declared = {name for name, _ in D13.FORBIDDEN_SHAPES}
        self.assertEqual(declared, covered,
                         'у каждой запрещённой формы обязан быть положительный контроль')


class RealPolicyUnchanged(unittest.TestCase):
    def test_real_policy_verdicts_are_not_weakened(self):
        self.assertEqual(WP.REAL_WEB_POLICY, {
            'REAL_CAPITAL_SUMMARY': 'BLOCKED',
            'REAL_POSITION_DETAIL': 'BLOCKED',
            'WALLET_ACCOUNT_IDENTIFIER': 'NEVER',
            'RAW_INVESTMENT_EVIDENCE': 'BLOCKED'})

    def test_introducing_a_real_field_does_not_publish_it(self):
        # Новое поле режима REAL закрыто по умолчанию, а не разрешено.
        stats = {}
        record = {'mode': 'REAL', 'some_brand_new_real_field': 'значение'}
        out = WP.project_real_record(record, stats)
        self.assertNotIn('значение', json.dumps(out, ensure_ascii=False))


class BlockedKeyListIsComplete(unittest.TestCase):
    def test_identity_columns_of_the_bridge_are_all_blocked(self):
        import bridge_evidence as BE
        blocked = {k.lower() for k in D13.BLOCKED_KEYS}
        # Колонки, которые обязаны быть перекрыты по имени. Остальные из списка моста
        # (например `error`, `path`) режутся по ФОРМЕ значения, и это отдельный рубеж.
        must = {'decided_by', 'confirmed_by', 'session_id', 'thread_id',
                'input_path', 'output_path', 'bundle_path', 'signature'}
        self.assertTrue(must <= blocked, f'не перекрыты: {sorted(must - blocked)}')
        self.assertTrue(must <= {c.lower() for c in BE.IDENTITY_COLUMNS})


if __name__ == '__main__':
    unittest.main()
