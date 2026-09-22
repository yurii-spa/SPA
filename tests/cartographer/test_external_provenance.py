"""Сторож провенанса внешних канонических входов (ARB A3, 22.09).

Требуемый инвариант, который держит этот набор:
    ТОТ ЖЕ код + ДРУГИЕ байты манифеста ⇒ ДРУГАЯ идентичность провенанса.

Авария, воспроизведённая здесь: идентичность выпуска Director считалась только по коду,
а ``architecture/manifest.json`` генерируется из ЖИВОЙ машины и питает свежесть по SLO,
раздел расхождений и счётчики служб. Замер того дня: прод 96 агентов, кандидат 98, код
один и тот же. Утверждение «хеш кода опознаёт владельческое состояние» было ложным.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'cartographer'))

import external_provenance as P            # noqa: E402

# FROZEN-DATE-OK: injected-clock — часы принимаются параметром `now` во всех вызовах
# (`observe_input(..., now=)`, `build_provenance(..., now=)`), а отметки файлов ставятся
# относительно ЭТОГО же `now` через os.utime, поэтому обе стороны закреплены.
NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def _tree(tmp, *, agents=96, contracts=None, manifest_age_h=1.0):
    root = Path(tmp)
    (root / 'architecture').mkdir(parents=True, exist_ok=True)
    m = root / 'architecture' / 'manifest.json'
    m.write_text(json.dumps({'agents': [{'label': f'a{i}'} for i in range(agents)]}),
                 encoding='utf-8')
    ts = (NOW - timedelta(hours=manifest_age_h)).timestamp()
    os.utime(m, (ts, ts))
    if contracts is not None:
        c = root / 'architecture' / 'health_contracts.json'
        c.write_text(json.dumps({'contracts': contracts}), encoding='utf-8')
        os.utime(c, (ts, ts))
    return root


class TheRequiredInvariant(unittest.TestCase):
    """Разные байты обязательного входа ⇒ разная идентичность провенанса."""

    def test_different_manifest_bytes_give_a_different_identity(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            ra = P.build_provenance(_tree(a, agents=96), now=NOW)
            rb = P.build_provenance(_tree(b, agents=98), now=NOW)
            self.assertNotEqual(ra['provenance_digest'], rb['provenance_digest'])
            self.assertEqual(ra['inputs'][0]['entry_count'], 96)
            self.assertEqual(rb['inputs'][0]['entry_count'], 98)

    def test_identical_bytes_give_the_same_identity(self):
        """Обратная сторона: без этого «разный» ничего бы не доказывал."""
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            ra = P.build_provenance(_tree(a, agents=96), now=NOW)
            rb = P.build_provenance(_tree(b, agents=96), now=NOW)
            self.assertEqual(ra['provenance_digest'], rb['provenance_digest'])

    def test_age_alone_does_not_move_the_identity(self):
        """Отпечаток отвечает на «те же ли входы», а не «когда смотрели».

        Иначе он менялся бы каждый час на неизменных файлах и перестал бы быть мерой.
        """
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            ra = P.build_provenance(_tree(a, agents=96, manifest_age_h=1.0), now=NOW)
            rb = P.build_provenance(_tree(b, agents=96, manifest_age_h=100.0), now=NOW)
            self.assertEqual(ra['provenance_digest'], rb['provenance_digest'])
            self.assertNotEqual(ra['inputs'][0]['age_hours'],
                                rb['inputs'][0]['age_hours'])


class ThirdOutcomeIsNeverZero(unittest.TestCase):
    """Инв. #17: отсутствие входа не ноль, не «свежо» и не успех."""

    def test_absent_required_input_is_not_measured(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / 'architecture').mkdir()
            r = P.build_provenance(tmp, now=NOW)
            row = r['inputs'][0]
            self.assertEqual(row['state'], 'NOT_MEASURED')
            self.assertIsNone(row['content_sha256'])
            self.assertIsNone(row['entry_count'])
            self.assertEqual(r['verdict'], 'NOT_MEASURED')
            self.assertIn('architecture/manifest.json', r['required_missing'])

    def test_absent_input_staleness_is_none_not_false(self):
        """О возрасте неизмеренного файла сказать нечего: None, а не «не протух»."""
        with TemporaryDirectory() as tmp:
            r = P.build_provenance(tmp, now=NOW)
            self.assertIsNone(r['inputs'][0]['stale'])
            self.assertNotEqual(r['inputs'][0]['stale'], False)

    def test_unreadable_input_is_not_measured_with_a_named_reason(self):
        with TemporaryDirectory() as tmp:
            root = _tree(tmp)
            (root / 'architecture' / 'manifest.json').write_text('{битый',
                                                                 encoding='utf-8')
            r = P.build_provenance(root, now=NOW)
            row = r['inputs'][0]
            self.assertEqual(row['state'], 'NOT_MEASURED')
            self.assertIn('не прочитан', row['reason'])

    def test_an_optional_absent_input_does_not_fail_the_verdict(self):
        """Необязательный вход отсутствует ⇒ вердикт OBSERVED, но вход НАЗВАН."""
        with TemporaryDirectory() as tmp:
            r = P.build_provenance(_tree(tmp), now=NOW)
            self.assertEqual(r['verdict'], 'OBSERVED')
            self.assertIn('architecture/health_contracts.json', r['unmeasured'])
            self.assertEqual(r['required_missing'], [])


class StalenessIsMeasuredAgainstADeclaredSlo(unittest.TestCase):

    def test_fresh_manifest_is_not_stale(self):
        with TemporaryDirectory() as tmp:
            r = P.build_provenance(_tree(tmp, manifest_age_h=1.0), now=NOW)
            self.assertFalse(r['inputs'][0]['stale'])

    def test_old_manifest_is_stale(self):
        with TemporaryDirectory() as tmp:
            r = P.build_provenance(_tree(tmp, manifest_age_h=54.0), now=NOW)
            self.assertTrue(r['inputs'][0]['stale'])
            self.assertGreater(r['inputs'][0]['age_hours'], 24.0)

    def test_an_input_without_a_declared_slo_has_no_staleness_verdict(self):
        """Порога нет ⇒ о протухании сказать нечего. None, а не False."""
        with TemporaryDirectory() as tmp:
            r = P.build_provenance(_tree(tmp, contracts=[{'x': 1}]), now=NOW)
            hc = [x for x in r['inputs']
                  if x['path'].endswith('health_contracts.json')][0]
            self.assertIsNone(hc['slo_hours'])
            self.assertIsNone(hc['stale'])


class ClassesAreDeclaredNotGuessed(unittest.TestCase):

    def test_manifest_is_a_required_canonical_external_input(self):
        spec = [s for s in P.DECLARED_INPUTS
                if s['path'] == 'architecture/manifest.json'][0]
        self.assertEqual(spec['input_class'], 'CANONICAL_EXTERNAL_INPUT')
        self.assertTrue(spec['required'])

    def test_health_contracts_is_optional(self):
        spec = [s for s in P.DECLARED_INPUTS
                if s['path'] == 'architecture/health_contracts.json'][0]
        self.assertEqual(spec['input_class'], 'OPTIONAL_EXTERNAL_INPUT')
        self.assertFalse(spec['required'])

    def test_no_declared_input_claims_release_population_membership(self):
        """Внешний вход не объявляется частью выпуска: это провенанс, не код."""
        with TemporaryDirectory() as tmp:
            r = P.build_provenance(_tree(tmp), now=NOW)
            for row in r['inputs']:
                self.assertFalse(row['release_population_member'], row['path'])


if __name__ == '__main__':
    unittest.main()
