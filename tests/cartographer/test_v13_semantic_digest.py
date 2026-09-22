"""Дайджест смысла v2: состязательные мутации.

Предыдущая схема вычитала из отпечатка список «волатильных» ключей, который вёлся
руками. Он протёк ТРИЖДЫ — `as_of`, `last_seen`, `detected_at`, — и причина не в
невнимательности, а в направлении умолчания: НОВОЕ поле попадало в отпечаток само.

Здесь умолчание обратное: в отпечаток входят только поля из объявленного списка
смысловых. Тесты ниже проверяют обе стороны — что шум НЕ двигает отпечаток и что
настоящее изменение двигает его обязательно. Проверка только одной стороны сделала бы
зелёной константу.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'cartographer'))

import owner_facts as F            # noqa: E402

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def base_facts():
    return [
        F.fact(domain='CAPITAL', metric='equity_now', value=101340.69, unit='USD',
               currency='USDC', currency_basis='data/capital_config.json:capital.currency',
               source='data/equity_curve_daily.json', source_field='summary.end_equity',
               observed_at='2026-09-20T06:00:00+00:00', slo_hours=30, now=NOW,
               web_visibility='SAFE_FOR_PRIVATE_WEB'),
        F.fact(domain='CAPITAL', metric='return_7d', value=0.083254, unit='%',
               source='data/equity_curve_daily.json', fact_kind='DERIVED',
               derivation='(close[t] / close[t-7] − 1) × 100',
               observed_at='2026-09-20T06:00:00+00:00', slo_hours=30, now=NOW),
        F.fact(domain='CAPITAL', metric='policy_compliant', value=False,
               source='data/current_positions.json',
               observed_at='2026-09-20T06:00:00+00:00', slo_hours=30, now=NOW),
    ]


class NoiseMustNotMove(unittest.TestCase):
    """Шум отпечаток не двигает."""

    def setUp(self):
        self.facts = base_facts()
        self.digest = F.semantic_digest(self.facts)

    def test_observation_timestamp_only(self):
        # РОВНО тот дефект, что нашёлся в v1.2 на detected_at красных флагов.
        for f in self.facts:
            f['observed_at'] = '2026-09-21T07:11:12+00:00'
        self.assertEqual(F.semantic_digest(self.facts), self.digest)

    def test_freshness_age_only(self):
        for f in self.facts:
            f['freshness_age_hours'] = 999.0
        self.assertEqual(F.semantic_digest(self.facts), self.digest)

    def test_list_reordering(self):
        shuffled = list(reversed(self.facts))
        self.assertEqual(F.semantic_digest(shuffled), self.digest)

    def test_derivation_text_rewording(self):
        self.facts[1]['derivation'] = 'отношение закрытий на концах окна, ×100'
        self.assertEqual(F.semantic_digest(self.facts), self.digest)

    def test_source_field_path_change(self):
        self.facts[0]['source_field'] = 'summary.close_equity'
        self.assertEqual(F.semantic_digest(self.facts), self.digest)

    def test_note_added(self):
        self.facts[0]['note'] = 'пояснение для владельца'
        self.assertEqual(F.semantic_digest(self.facts), self.digest)

    def test_brand_new_undeclared_field(self):
        # Главное свойство схемы: поле, появившееся завтра, отпечаток НЕ двигает,
        # пока его не объявят смысловым. В прежней схеме было наоборот.
        for f in self.facts:
            f['checked_at'] = '2026-09-21T09:00:00+00:00'
            f['some_future_telemetry'] = 12345
        self.assertEqual(F.semantic_digest(self.facts), self.digest)


class RealChangeMustMove(unittest.TestCase):
    """Настоящее изменение смысла отпечаток двигает обязательно."""

    def setUp(self):
        self.facts = base_facts()
        self.digest = F.semantic_digest(self.facts)

    def assert_moved(self, why):
        self.assertNotEqual(F.semantic_digest(self.facts), self.digest, why)

    def test_value_change(self):
        self.facts[0]['value'] = 101340.70
        self.assert_moved('изменение суммы обязано двигать отпечаток')

    def test_boolean_flip(self):
        self.facts[2]['value'] = True
        self.assert_moved('смена соответствия политике обязана двигать отпечаток')

    def test_missing_versus_zero(self):
        self.facts[1]['value'] = 0
        zero = F.semantic_digest(self.facts)
        self.facts[1]['value'] = None
        self.facts[1]['absent_reason'] = 'источник не объявил'
        absent = F.semantic_digest(self.facts)
        self.assertNotEqual(zero, absent,
                            'ноль и «не измерено» обязаны различаться в отпечатке')
        self.assertNotEqual(zero, self.digest)

    def test_unknown_versus_false(self):
        self.facts[2]['value'] = None
        self.facts[2]['absent_reason'] = 'источник не объявил'
        unknown = F.semantic_digest(self.facts)
        self.facts[2]['value'] = False
        self.facts[2]['absent_reason'] = None
        self.assertNotEqual(unknown, F.semantic_digest(self.facts))

    def test_stale_to_fresh(self):
        self.facts[0]['freshness_state'] = 'STALE'
        self.assert_moved('смена состояния свежести меняет смысл для владельца')

    def test_conflict_added(self):
        self.facts[0]['verification_state'] = 'CONFLICT'
        self.facts[0]['conflict_count'] = 1
        self.assert_moved('появление расхождения источников — изменение смысла')

    def test_conflict_removed(self):
        self.facts[0]['verification_state'] = 'CONFLICT'
        self.facts[0]['conflict_count'] = 1
        with_conflict = F.semantic_digest(self.facts)
        self.facts[0]['verification_state'] = 'VERIFIED'
        self.facts[0]['conflict_count'] = 0
        self.assertNotEqual(with_conflict, F.semantic_digest(self.facts))

    def test_currency_change(self):
        self.facts[0]['currency'] = 'USD'
        self.assert_moved('смена валюты — изменение смысла суммы')

    def test_mode_change(self):
        self.facts[0]['mode'] = 'REAL'
        self.assert_moved('смена режима капитала — важнейшее изменение смысла')

    def test_observation_kind_change(self):
        self.facts[0]['observation_kind'] = 'TARGET_POLICY'
        self.assert_moved('наблюдение, ставшее целью, — другое утверждение')

    def test_owner_relevance_change(self):
        self.facts[2]['owner_relevance'] = 'DECISION_REQUIRED'
        self.assert_moved('появление требования решения меняет смысл экрана')

    def test_fact_removed(self):
        self.facts.pop()
        self.assert_moved('исчезновение факта — изменение состава экрана')

    def test_fact_added(self):
        self.facts.append(F.not_measured(domain='CAPITAL', metric='benchmark',
                                         source='—', reason='источника нет'))
        self.assert_moved('появление нового факта — изменение состава экрана')


class Determinism(unittest.TestCase):
    def test_repeated_builds_are_identical(self):
        digests = {F.semantic_digest(base_facts()) for _ in range(10)}
        self.assertEqual(len(digests), 1)

    def test_semantic_field_list_has_no_clock_fields(self):
        # Положительный контроль самой схемы: отметка времени в списке смысловых
        # вернула бы ровно прежний дефект.
        for name in F.SEMANTIC_FACT_FIELDS:
            for clock in ('_at', 'age', 'time', 'stamp', 'seen'):
                self.assertNotIn(clock, name,
                                 f'поле {name} похоже на отметку времени и не может '
                                 f'быть смысловым')


if __name__ == '__main__':
    unittest.main()
