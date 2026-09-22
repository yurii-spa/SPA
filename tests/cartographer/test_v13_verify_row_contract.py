"""Сторож полноты строки сверки (director_verify.compare) и охраны отсутствия слоя.

Каждый тест — положительный контроль настоящей поломки, а не украшение.

Авария 22.09, воспроизведённая здесь дословно: агрегат `compare()` читал
``r['metric_class']`` у КАЖДОЙ строки, а две ветки — ``NOT_PUBLISHED`` и
``BOTH_NOT_MEASURED`` — этот ключ не кладут, и независимая сверка выпуска умирала
``KeyError: 'metric_class'`` ровно на том исходе, ради честности о котором написана.
Ни один тест набора эти две ветки не называл, поэтому 7 244 зелёных теста молчали.

Второе, найденное тем же замером: при отсутствии слоя ``v13`` прежний откат
``projection.get('v13') or projection`` превращал ОДНО отсутствие документа в двадцать
одну строку уровня величин (16 «не опубликовано», 5 «расхождение») при НУЛЕ строк
``AGREE``. Ноль совпадений на полном населении и есть улика того, что сравнивать было
нечего: это НЕ ИЗМЕРЕНО, а не находка о кокпите (инв. #17).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'cartographer'))

import director_verify as V            # noqa: E402


def _projection(*facts):
    """Проекция минимальной формы: список фактов, как их кладёт слой v13."""
    return {'facts': [{'metric': m, 'value': v} for m, v in facts]}


class RowSchemaIsTotal(unittest.TestCase):
    """У каждой строки обязаны быть ВСЕ ключи контракта — во всех ветках."""

    def _rows(self, projection, measured):
        return {r['metric']: r for r in V.compare(projection, measured)['rows']}

    def test_published_row_carries_the_whole_contract(self):
        r = self._rows(_projection(('equity_now', 100.0)), {'equity_now': 100.0})
        self.assertEqual(set(V.ROW_KEYS) - set(r['equity_now']), set())
        self.assertEqual(r['equity_now']['verdict'], 'AGREE')

    def test_not_published_row_carries_the_whole_contract(self):
        """Ветка, на которой сверка умирала KeyError'ом."""
        r = self._rows(_projection(), {'equity_now': 100.0})
        self.assertEqual(set(V.ROW_KEYS) - set(r['equity_now']), set())
        self.assertEqual(r['equity_now']['verdict'], 'NOT_PUBLISHED')

    def test_both_not_measured_row_carries_the_whole_contract(self):
        """Вторая ветка, на которой сверка умирала KeyError'ом."""
        r = self._rows(_projection(('equity_now', None)), {'equity_now': None})
        self.assertEqual(set(V.ROW_KEYS) - set(r['equity_now']), set())
        self.assertEqual(r['equity_now']['verdict'], 'BOTH_NOT_MEASURED')

    def test_absence_does_not_get_a_real_metric_class(self):
        """Отсутствие обязано быть ТРЕТЬИМ значением класса, а не «устойчивым».

        Приписать неопубликованному числу настоящий класс значило бы впустить любое
        отсутствие в дверь «законно расходится» и выдать НЕ ИЗМЕРЕНО за наблюдение.
        """
        self.assertIn('equity_now', V.STABLE_METRICS)   # предпосылка стенда
        r = self._rows(_projection(), {'equity_now': 100.0})
        self.assertEqual(r['equity_now']['metric_class'], V.NOT_MEASURED_CLASS)
        self.assertNotEqual(r['equity_now']['metric_class'], 'STABLE')

    def test_a_published_stable_metric_keeps_its_real_class(self):
        """Обратная сторона: у НАБЛЮДЁННОЙ величины класс настоящий, не третий."""
        r = self._rows(_projection(('equity_now', 100.0)), {'equity_now': 100.0})
        self.assertEqual(r['equity_now']['metric_class'], 'STABLE')


class AggregationHandlesEveryShape(unittest.TestCase):
    """Смешанный набор строк в ОДНОЙ сверке — та форма, что ломала агрегат."""

    def setUp(self):
        self.measured = {'equity_now': 100.0,          # опубликовано и совпадает
                         'cash_usd': 5.0,              # НЕ опубликовано
                         'return_1d': None,            # не измерено обеими сторонами
                         'net_pnl_usd': 7.0}           # опубликовано и РАСХОДИТСЯ
        self.projection = _projection(('equity_now', 100.0), ('return_1d', None),
                                      ('net_pnl_usd', 9.0))

    def test_mixed_rows_do_not_raise(self):
        result = V.compare(self.projection, self.measured)
        self.assertEqual(len(result['rows']), 4)

    def test_every_third_outcome_is_named_not_omitted(self):
        result = V.compare(self.projection, self.measured)
        self.assertEqual(result['not_published'], ['cash_usd'])
        self.assertEqual(result['both_not_measured'], ['return_1d'])

    def test_a_real_mismatch_still_fails_the_release(self):
        """Починка не смягчила вердикт: расхождение устойчивой величины — отказ."""
        result = V.compare(self.projection, self.measured)
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(result['mismatches'], 1)

    def test_an_all_agreeing_comparison_passes(self):
        """Контроль в другую сторону: без расхождений вердикт PASS."""
        result = V.compare(_projection(('equity_now', 100.0)), {'equity_now': 100.0})
        self.assertEqual(result['verdict'], 'PASS')


class MalformedRowStillFails(unittest.TestCase):
    """Обратный контроль: строка, ПРАВДА нарушающая контракт, обязана ронять сверку."""

    def test_a_row_without_metric_class_is_refused_by_name(self):
        with self.assertRaises(ValueError) as ctx:
            V._assert_row_contract([{'metric': 'equity_now', 'independent': 1,
                                     'director': 1, 'verdict': 'AGREE'}])
        self.assertIn('equity_now', str(ctx.exception))
        self.assertIn('metric_class', str(ctx.exception))

    def test_a_complete_row_is_accepted(self):
        V._assert_row_contract([{'metric': 'equity_now', 'independent': 1, 'director': 1,
                                 'verdict': 'AGREE', 'metric_class': 'STABLE'}])

    def test_the_refusal_names_every_offending_row(self):
        with self.assertRaises(ValueError) as ctx:
            V._assert_row_contract([
                {'metric': 'a', 'independent': 1, 'director': 1, 'verdict': 'AGREE'},
                {'metric': 'b', 'independent': 1, 'director': 1, 'verdict': 'AGREE',
                 'metric_class': 'STABLE'},
                {'metric': 'c', 'independent': 1, 'director': 1, 'verdict': 'AGREE'}])
        self.assertIn('a', str(ctx.exception))
        self.assertIn('c', str(ctx.exception))


class MissingLayerIsNotMeasured(unittest.TestCase):
    """Отсутствие слоя v13 — НЕ ИЗМЕРЕНО, а не двадцать одна находка о кокпите."""

    def test_projection_without_v13_is_named_not_measured(self):
        why = V.missing_v13_layer({'layers': {}, 'semantic_digest': 'x'})
        self.assertIsNotNone(why)
        self.assertIn('v13', why)

    def test_empty_v13_is_named_not_measured(self):
        self.assertIsNotNone(V.missing_v13_layer({'v13': {}}))

    def test_a_non_dict_projection_is_named_not_measured(self):
        self.assertIsNotNone(V.missing_v13_layer(['не словарь']))

    def test_a_present_v13_layer_is_accepted(self):
        """Контроль в другую сторону: со слоем охрана молчит."""
        self.assertIsNone(V.missing_v13_layer({'v13': {'facts': []}}))


if __name__ == '__main__':
    unittest.main()
