"""Контракт правды v1.3: паспорт факта, канонические расчёты, дайджест смысла.

Каждый тест здесь — положительный контроль найденного дефекта. Тест, который никогда
не видел настоящей поломки, — украшение; поэтому у каждого назван дефект, который он
воспроизводит.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'cartographer'))

import owner_facts as F            # noqa: E402
import capital_truth as CT         # noqa: E402

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)


def series(rows):
    """Ряд из (дата, закрытие[, признаки])."""
    out = []
    for row in rows:
        d, eq = row[0], row[1]
        extra = row[2] if len(row) > 2 else {}
        out.append({'date': d, 'close_equity': eq, **extra})
    return out


class FactPassport(unittest.TestCase):
    """Факт без паспорта собрать НЕЛЬЗЯ — в этом весь смысл контракта."""

    def test_source_is_mandatory(self):
        with self.assertRaises(F.FactError):
            F.fact(domain='CAPITAL', metric='x', value=1, source=None)

    def test_derived_without_formula_is_refused(self):
        # Дефект v1.2: доход за 7 дней считался неверной формулой, и формулы нигде не было.
        with self.assertRaises(F.FactError):
            F.fact(domain='CAPITAL', metric='r7', value=1, source='s', fact_kind='DERIVED')

    def test_observed_with_formula_is_refused(self):
        with self.assertRaises(F.FactError):
            F.fact(domain='CAPITAL', metric='e', value=1, source='s',
                   fact_kind='OBSERVED', derivation='a/b')

    def test_currency_without_declaration_is_refused(self):
        # Дефект v1.2: экран печатал «эквити, USDC», а ряд валюту не объявляет.
        with self.assertRaises(F.FactError):
            F.fact(domain='CAPITAL', metric='e', value=1, source='s', currency='USDC')

    def test_currency_with_declaration_is_allowed(self):
        f = F.fact(domain='CAPITAL', metric='e', value=1, source='s', currency='USDC',
                   currency_basis='data/capital_config.json:capital.currency')
        self.assertEqual(f['currency'], 'USDC')

    def test_missing_value_requires_a_named_reason(self):
        # Инвариант #17: отсутствие наблюдения обязано быть названо, а не стать нулём.
        with self.assertRaises(F.FactError):
            F.fact(domain='CAPITAL', metric='e', value=None, source='s')
        f = F.not_measured(domain='CAPITAL', metric='e', source='s', reason='нет поля')
        self.assertIsNone(f['value'])
        self.assertEqual(f['absent_reason'], 'нет поля')

    def test_zero_is_not_absence(self):
        f = F.fact(domain='CAPITAL', metric='dd', value=0, source='s')
        self.assertEqual(f['value'], 0)
        self.assertIsNone(f['absent_reason'])

    def test_conflict_must_carry_its_description(self):
        with self.assertRaises(F.FactError):
            F.fact(domain='C', metric='m', value=1, source='s',
                   verification_state='CONFLICT')

    def test_conflict_never_overwrites_the_value(self):
        base = F.fact(domain='C', metric='m', value=10.0, source='s')
        out = F.with_conflict(base, other_value=11.0, other_source='свой пересчёт')
        self.assertEqual(out['value'], 10.0)          # значение НЕ подменено
        self.assertEqual(out['verification_state'], 'CONFLICT')
        self.assertEqual(out['conflicts'][0]['other_value'], 11.0)

    def test_freshness_without_declared_slo_is_not_measured(self):
        f = F.fact(domain='C', metric='m', value=1, source='s',
                   observed_at='2026-09-21T11:00:00+00:00', now=NOW)
        self.assertEqual(f['freshness_state'], 'NOT_MEASURED')


class CanonicalReturns(unittest.TestCase):
    """Одна формула окна на всю систему, и она отношение, а не разность накопленных."""

    def test_window_uses_ratio_not_difference_of_cumulative(self):
        # ДЕФЕКТ v1.2 в лабораторных величинах: на удвоениях ошибка становится грубой.
        pts, _ = F.parse_series(series([
            ('2026-01-01', 100.0), ('2026-01-02', 200.0), ('2026-01-03', 400.0)]))
        r = F.window_return(pts, 1)
        self.assertAlmostEqual(r['value'], 100.0, places=6)      # 400/200 − 1 = +100 %
        # метод v1.2 (разность накопленных) дал бы 300 − 100 = 200 п.п.
        self.assertNotAlmostEqual(r['value'], 200.0, places=6)

    def test_two_day_window_over_doublings(self):
        pts, _ = F.parse_series(series([
            ('2026-01-01', 100.0), ('2026-01-02', 200.0), ('2026-01-03', 400.0)]))
        self.assertAlmostEqual(F.window_return(pts, 2)['value'], 300.0, places=6)

    def test_window_is_calendar_not_positional(self):
        # Пропущенный день не превращает «7 дней» в «7 точек».
        rows = [('2026-01-01', 100.0), ('2026-01-02', 101.0), ('2026-01-04', 102.0)]
        pts, _ = F.parse_series(series(rows))
        r = F.window_return(pts, 2)
        self.assertEqual(r['start_date'], '2026-01-02')
        self.assertEqual(r['window_actual_days'], 2)

    def test_missing_exact_date_is_named_not_silently_substituted(self):
        rows = [('2026-01-01', 100.0), ('2026-01-02', 101.0), ('2026-01-04', 102.0)]
        pts, _ = F.parse_series(series(rows))
        r = F.window_return(pts, 1)          # 03.01 в ряду нет
        self.assertEqual(r['precision'], 'NEAREST_BEFORE')
        self.assertNotEqual(r['window_actual_days'], 1)

    def test_window_crossing_a_declared_break_refuses(self):
        # ДЕФЕКТ: метрика сквозь разрыв ряда меряет склейку серий, а не капитал.
        rows = series([('2026-01-01', 100.0), ('2026-01-02', 101.0),
                       ('2026-01-03', 90.0, {'series_reset': True}),
                       ('2026-01-04', 91.0)])
        pts, _ = F.parse_series(rows)
        b = F.series_boundaries(pts)
        self.assertEqual([d.isoformat() for d in b], ['2026-01-03'])
        r = F.window_return(pts, 3, boundaries=b)
        self.assertEqual(r['state'], 'NOT_MEASURED')
        self.assertIn('разрыв', r['reason'])

    def test_declared_base_zero_is_not_replaced(self):
        # Объявленный ноль — объявленный, а не «пусто».
        pts, _ = F.parse_series(series([('2026-01-01', 100.0), ('2026-01-02', 110.0)]))
        r = F.total_return(pts, declared_base=0, declared_base_field='x')
        self.assertEqual(r['state'], 'NOT_MEASURED')


class Drawdowns(unittest.TestCase):
    """Две просадки — две величины. И разрыв ряда просадкой не является."""

    def test_max_and_current_are_different_quantities(self):
        pts, _ = F.parse_series(series([
            ('2026-01-01', 100.0), ('2026-01-02', 90.0), ('2026-01-03', 100.0)]))
        self.assertAlmostEqual(F.max_drawdown(pts)['value'], -10.0, places=6)
        self.assertAlmostEqual(F.current_drawdown(pts)['value'], 0.0, places=6)

    def test_series_break_resets_the_peak(self):
        # ДЕФЕКТ v1.2: −0.2047 % «просадки» были ступенью между сериями.
        rows = series([('2026-01-01', 100.0), ('2026-01-02', 120.0),
                       ('2026-01-03', 100.0, {'series_reset': True}),
                       ('2026-01-04', 99.0)])
        pts, _ = F.parse_series(rows)
        b = F.series_boundaries(pts)
        naive = F.max_drawdown(pts)['value']
        aware = F.max_drawdown(pts, boundaries=b)['value']
        self.assertAlmostEqual(naive, -17.5, places=4)      # считает склейку
        self.assertAlmostEqual(aware, -1.0, places=4)       # считает капитал
        self.assertNotAlmostEqual(naive, aware, places=4)


class CalendarIntegrity(unittest.TestCase):
    def test_missing_dates_are_listed_not_hidden(self):
        pts, _ = F.parse_series(series([('2026-01-01', 1.0), ('2026-01-04', 2.0)]))
        ci = F.calendar_integrity(pts)
        self.assertEqual(ci['missing_dates'], ['2026-01-02', '2026-01-03'])
        self.assertFalse(ci['is_continuous'])

    def test_duplicates_are_reported(self):
        pts, _ = F.parse_series(series([('2026-01-01', 1.0), ('2026-01-01', 2.0)]))
        self.assertEqual(F.calendar_integrity(pts)['duplicate_count'], 1)

    def test_dropped_rows_are_counted_not_silently_lost(self):
        rows = series([('2026-01-01', 1.0)]) + [{'date': None, 'close_equity': 5.0},
                                                {'date': '2026-01-02'}]
        pts, dropped = F.parse_series(rows)
        self.assertEqual(len(pts), 1)
        self.assertEqual(dropped, 2)


if __name__ == '__main__':
    unittest.main()
