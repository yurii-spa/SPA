"""Долговечность истории: неизменяемость прошлого, горизонт буфера, честность сторожа.

Каждый класс воспроизводит настоящую находку замера, а не воображаемую.
"""
import json
import sys
import tarfile
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'cartographer'))

import history_durability as hd      # noqa: E402

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 21)


def row(d, equity, *, evidenced=True, source='cycle'):
    return {'date': d, 'open_equity': equity - 1, 'close_equity': equity,
            'daily_return_pct': 0.01, 'cumulative_return_pct': 0.1,
            'drawdown_pct': 0.0, 'evidenced': evidenced, 'source': source}


SERIES = [row('2026-09-18', 100.0), row('2026-09-19', 101.0),
          row('2026-09-20', 102.0), row('2026-09-21', 103.0)]


class ClosedDayLedger(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='ledger-'))
        self.path = self.dir / 'l.json'

    def test_first_run_appends_closed_days_only(self):
        r = hd.update_ledger(SERIES, ledger_path=self.path, today=TODAY, now=NOW)
        # 21.09 ещё дописывается циклом — закрытым днём он не является.
        self.assertEqual(r['appended_count'], 3)
        self.assertNotIn('2026-09-21', r['ledger']['days'])

    def test_second_run_is_idempotent(self):
        hd.update_ledger(SERIES, ledger_path=self.path, today=TODAY, now=NOW)
        r = hd.update_ledger(SERIES, ledger_path=self.path, today=TODAY, now=NOW)
        self.assertEqual((r['appended_count'], r['rewritten_count']), (0, 0))
        self.assertEqual(r['unchanged_count'], 3)
        self.assertEqual(r['verdict'], 'IMMUTABLE')

    def test_rewriting_a_closed_day_is_a_finding(self):
        # Замер по истории git: семь коммитов переписали 90 закрытых дат.
        hd.update_ledger(SERIES, ledger_path=self.path, today=TODAY, now=NOW)
        tampered = [dict(r) for r in SERIES]
        tampered[1]['close_equity'] = 900.0
        r = hd.update_ledger(tampered, ledger_path=self.path, today=TODAY, now=NOW,
                             write=False)
        self.assertEqual(r['verdict'], 'PAST_REWRITTEN')
        self.assertEqual(r['rewritten_count'], 1)
        self.assertEqual(r['rewritten'][0]['date'], '2026-09-19')
        self.assertEqual(r['rewritten'][0]['close_equity_now'], 900.0)

    def test_appending_a_new_day_is_not_a_rewrite(self):
        hd.update_ledger(SERIES, ledger_path=self.path, today=TODAY, now=NOW)
        later = SERIES + [row('2026-09-22', 104.0)]
        r = hd.update_ledger(later, ledger_path=self.path,
                             today=date(2026, 9, 23), now=NOW, write=False)
        self.assertEqual(r['rewritten_count'], 0)
        self.assertGreaterEqual(r['appended_count'], 1)

    def test_unreadable_ledger_is_not_measured_and_not_overwritten(self):
        # Нечитаемый журнал ≠ отсутствующий: создать новый поверх стёрло бы улику.
        self.path.write_text('{ сломано', encoding='utf-8')
        r = hd.update_ledger(SERIES, ledger_path=self.path, today=TODAY, now=NOW,
                             write=False)
        self.assertEqual(r['state'], 'NOT_MEASURED')
        self.assertIn('стёрло бы улику', r['reason'])

    def test_digest_ignores_fields_outside_the_declared_list(self):
        hd.update_ledger(SERIES, ledger_path=self.path, today=TODAY, now=NOW)
        noisy = [dict(r, some_new_telemetry=123, checked_at='сейчас') for r in SERIES]
        r = hd.update_ledger(noisy, ledger_path=self.path, today=TODAY, now=NOW,
                             write=False)
        self.assertEqual(r['rewritten_count'], 0,
                         'новое поле не объявляет прошлое переписанным')

    def test_digest_moves_on_a_declared_field(self):
        a = hd.point_digest(row('2026-01-01', 1.0))
        b = hd.point_digest(row('2026-01-01', 2.0))
        self.assertNotEqual(a, b)

    def test_ledger_digest_is_order_independent(self):
        hd.update_ledger(SERIES, ledger_path=self.path, today=TODAY, now=NOW)
        first = hd.load_ledger(self.path)['ledger_digest']
        other = self.dir / 'l2.json'
        hd.update_ledger(list(reversed(SERIES)), ledger_path=other, today=TODAY, now=NOW)
        self.assertEqual(first, hd.load_ledger(other)['ledger_digest'])


class RingBufferHorizon(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='ring-'))
        (self.root / 'spa_core' / 'paper_trading').mkdir(parents=True)

    def _declare(self, text):
        (self.root / hd.RING_CAP_DECL[0]).write_text(text, encoding='utf-8')

    def test_cap_is_read_from_the_source_not_hardcoded(self):
        self._declare('MAX_EQUITY_POINTS = 7    # ring-buffer cap\n')
        cap, basis = hd.read_ring_cap(self.root)
        self.assertEqual(cap, 7)
        self.assertIn(hd.RING_CAP_DECL[0], basis)

    def test_absent_declaration_is_not_measured(self):
        self._declare('SOMETHING_ELSE = 1\n')
        r = hd.ring_buffer_horizon(SERIES, production_root=self.root, now=NOW)
        self.assertEqual(r['state'], 'NOT_MEASURED')

    def test_horizon_counts_remaining_days(self):
        self._declare('MAX_EQUITY_POINTS = 10\n')
        r = hd.ring_buffer_horizon(SERIES, production_root=self.root, now=NOW)
        self.assertEqual(r['days_until_truncation'], 6)
        self.assertEqual(r['first_point_at_risk'], '2026-09-18')

    def test_warning_fires_inside_the_declared_horizon(self):
        self._declare('MAX_EQUITY_POINTS = 5\n')
        self.assertTrue(hd.ring_buffer_horizon(SERIES, production_root=self.root,
                                               now=NOW)['warning'])

    def test_already_truncating_is_named(self):
        self._declare('MAX_EQUITY_POINTS = 2\n')
        r = hd.ring_buffer_horizon(SERIES, production_root=self.root, now=NOW)
        self.assertLess(r['days_until_truncation'], 0)
        self.assertEqual(r['estimated_truncation_date'], 'уже обрезается')


class BackupClaimHonesty(unittest.TestCase):
    """Сторож отвечал «ok» об отсутствующем архиве. И мой прибор сначала ошибся тоже."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='backups-'))
        for day in ('20260918', '20260919', '20260920'):
            (self.dir / f'spa_state_{day}T051500Z.tar.gz').write_bytes(b'x')

    def test_archive_days_are_parsed_from_names(self):
        self.assertEqual(hd.archive_days(self.dir),
                         {'2026-09-18', '2026-09-19', '2026-09-20'})

    def test_missing_directory_is_not_measured(self):
        self.assertIsNone(hd.archive_days(self.dir / 'нет'))

    def test_ok_claim_without_archive_inside_the_window_is_caught(self):
        claims = {'2026-09-18': {'state': 'ok'}, '2026-09-19': {'state': 'ok'},
                  '2026-09-20': {'state': 'ok'}}
        del claims['2026-09-19']
        claims['2026-09-19'] = {'state': 'ok'}
        (self.dir / 'spa_state_20260919T051500Z.tar.gz').unlink()
        r = hd.verify_backup_claims(claims=claims, backup_dir=self.dir)
        self.assertEqual(r['verdict'], 'GUARD_REPORTS_OK_FOR_MISSING_ARCHIVE')
        self.assertEqual(r['days_claimed_ok_without_archive'], ['2026-09-19'])

    def test_days_outside_the_retention_window_are_not_judged(self):
        # Ровно ошибка первой редакции: она насчитала 17 дефектов, из них 16 были её
        # собственной ошибкой — архивы за август просто вычищены по сроку хранения.
        claims = {'2026-08-01': {'state': 'ok'}, '2026-09-18': {'state': 'ok'}}
        r = hd.verify_backup_claims(claims=claims, backup_dir=self.dir)
        self.assertEqual(r['days_outside_window'], ['2026-08-01'])
        self.assertEqual(r['false_ok_count'], 0)
        self.assertEqual(r['verdict'], 'HONEST')

    def test_all_claims_matching_is_honest(self):
        claims = {d: {'state': 'ok'} for d in
                  ('2026-09-18', '2026-09-19', '2026-09-20')}
        self.assertEqual(hd.verify_backup_claims(
            claims=claims, backup_dir=self.dir)['verdict'], 'HONEST')

    def test_empty_backup_directory_is_not_measured(self):
        empty = Path(tempfile.mkdtemp(prefix='empty-'))
        r = hd.verify_backup_claims(claims={'2026-09-18': {'state': 'ok'}},
                                    backup_dir=empty)
        self.assertEqual(r['state'], 'NOT_MEASURED')


class ArchiveMembership(unittest.TestCase):
    """«Файл в архиве» проверяется чтением архива, а не именем скрипта."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='arch-'))
        payload = self.dir / 'equity_curve_daily.json'
        payload.write_text('{}', encoding='utf-8')
        self.archive = self.dir / 'a.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as t:
            t.add(payload, arcname='equity_curve_daily.json')

    def test_present_member_is_found(self):
        r = hd.archive_contains(self.archive, 'equity_curve_daily.json')
        self.assertEqual(r['state'], 'PRESENT')

    def test_absent_member_is_absent_not_unmeasured(self):
        self.assertEqual(hd.archive_contains(self.archive, 'нетакого.json')['state'],
                         'ABSENT')

    def test_missing_archive_is_not_measured(self):
        self.assertEqual(hd.archive_contains(self.dir / 'нет.tar.gz', 'x')['state'],
                         'NOT_MEASURED')


if __name__ == '__main__':
    unittest.main()
