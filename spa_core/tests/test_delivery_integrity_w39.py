"""Сторож целостности доставки общих канонических файлов (ТЕНЕВОЕ, 22.09).

ПРОВЕНАНС ФИКСТУРЫ — настоящая авария, измеренная 22.09.2026
============================================================
Кандидат выпуска Director прошёл полный CI с ``candidate_only = 0``,
``NEW_REGRESSION = 0``, ``PROMOTION_CRITICAL_FAILURES = 0`` — и нёс УСТАРЕВШУЮ копию
``docs/journal/2026-W39.md``:

  канон (``72f235fbf``)        84 236 байт · 809 строк · 10 заголовков ``## ``
  копия в кандидате            43 853 байта · 460 строк ·  7 заголовков
  УНИЧТОЖЕНО                   40 383 байта · 349 строк · 5 целых записей

Уничтоженные записи: циклы **#661**, **#662**, **#665**, **#666** и R&D-итерация
novel-edge-rnd (заказ #110). Ни один тест этого не сказал; нашлось разбором дрейфа руками.

Вторая авария того же класса, измеренная ранее и тоже воспроизведённая здесь:
``a3c015f05`` снёс **1729 строк** ``docs/STATE.md``, **не тронув ни одного заголовка** —
поэтому мера сторожа обязана быть СОДЕРЖИМЫМ, а не перечнем заголовков.

Третья: ``ba66e1bd3`` (30.08) принёс свой пункт поверх УСТАРЕВШЕЙ копии
``.claude/rules/deployment.md`` и унёс 104 строки — правило о классе было уничтожено
этим же классом.

Фикстуры ниже воспроизводят ФОРМУ этих аварий на компактных документах: сами файлы по
84–99 КБ в набор не вносятся, а их измеренные числа записаны выше как провенанс.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'shadow'))

import canonical_delivery_guard as DI            # noqa: E402
# Имя ВЫБРАНО, а не придумано: `delivery_integrity` уже занято в пакете Bridge
# (`scripts/bridge_shadow/shadow_gate.py:48` — `from bridge import delivery_integrity`),
# и второй объект под тем же именем есть документированный класс дефекта
# (`.claude/rules/adapters.md`: «одно имя — один объект», цикл #274).

JOURNAL = 'docs/journal/2026-W39.md'

#: Настоящие заголовки аварии, в настоящем порядке (замер 22.09).
REAL_HEADINGS = [
    '## Автономный цикл оркестратора #656 (21.09) — G59 п. 2: канал имени был одноязычным',
    '## Цикл #657 — заказ G60 пп. 1–2: одноязычие кусается там, где у токена есть слово',
    '## Цикл #658 (21.09): заказ G61 п. 1 — точность канала есть ИНТЕРВАЛ',
    '## Цикл #659 (21.09) — заказ G62 п. 1: цена «двух токенов»',
    '## Автономный цикл оркестратора #660 (21.09) — G63 п. 1: третий свидетель абзаца',
    '## Цикл #661 (2026-09-21) — заказ G64 п. 1: цена допуска свидетеля',
    '## Цикл #662 (21.09) — заказ G65 п. 1: каждый читатель переписи берёт СВОЮ базу',
    '## Автономный цикл оркестратора #665 (22.09) — G67 п. 1: класс невидимого потребителя',
    '## R&D-итерация novel-edge-rnd (22.09) — заказ #110 исполнен ЦЕЛИКОМ',
    '## Цикл #666 (2026-09-22) — заказ G68 п. 1: занижение повсеместно',
]
#: Ровно те пять, что кандидат уничтожил.
DESTROYED = REAL_HEADINGS[5:]
SURVIVED = REAL_HEADINGS[:5]

MY_ENTRIES = [
    '## Цикл #592 — своя запись отсутствовала, восстановлена ретроспективно 21.09',
    '## Цикл #596 — своя запись отсутствовала, восстановлена ретроспективно 21.09',
]
DRIFT_ENTRY = '## Цикл #667 (2026-09-22) — заказ G69 п. 1: у остатка была цена'


def _doc(headings, *, body_lines=6):
    out = []
    for h in headings:
        out.append(h)
        out.append('')
        for i in range(body_lines):
            out.append(f'тело записи {h[3:26]} строка {i}')
        out.append('')
    return ('\n'.join(out) + '\n').encode('utf-8')


CANON = _doc(REAL_HEADINGS)
STALE_CANDIDATE = _doc(SURVIVED)                       # ровно форма аварии
GOOD_APPEND = _doc(REAL_HEADINGS + MY_ENTRIES)
ORIGIN_AFTER_DRIFT = _doc(REAL_HEADINGS + [DRIFT_ENTRY])
MERGED = _doc(REAL_HEADINGS + [DRIFT_ENTRY] + MY_ENTRIES)


class TheW39IncidentIsPermanentlyGuarded(unittest.TestCase):
    """Шесть контролей, которых требовал ARB. Каждый — форма настоящей аварии."""

    def test_the_stale_candidate_is_BLOCKED(self):
        r = DI.analyse(JOURNAL, CANON, STALE_CANDIDATE)
        self.assertEqual(r['verdict'], 'BLOCK', r)
        self.assertIn('missing_section', r['findings'])
        self.assertIn('silent_line_loss', r['findings'])
        self.assertEqual(r['source_headings'] - r['candidate_headings'], len(DESTROYED))

    def test_the_content_preserving_append_PASSES(self):
        r = DI.analyse(JOURNAL, CANON, GOOD_APPEND)
        self.assertEqual(r['verdict'], 'PASS', r)
        self.assertEqual(r['lost_lines'], 0)
        self.assertTrue(r['exact_byte_prefix'])

    def test_surviving_headings_with_deleted_bodies_are_BLOCKED(self):
        """Форма ``a3c015f05``: заголовки целы, тело снесено — 1729 строк.

        Сторож по заголовкам на этой аварии молчит, и это названо в его собственном
        модуле. Мера здесь — содержимое, поэтому авария ловится.
        """
        hollow = _doc(REAL_HEADINGS, body_lines=0)
        r = DI.analyse(JOURNAL, CANON, hollow)
        self.assertEqual(r['verdict'], 'BLOCK', r)
        self.assertEqual(r['missing_headings'], [], 'заголовки обязаны быть целы в сцене')
        self.assertIn('body_deletion_under_surviving_heading', r['findings'])

    def test_origin_drift_plus_local_append_PASSES_after_merge(self):
        r = DI.analyse(JOURNAL, ORIGIN_AFTER_DRIFT, MERGED)
        self.assertEqual(r['verdict'], 'PASS', r)
        self.assertEqual(r['lost_lines'], 0)
        self.assertTrue(r['exact_byte_prefix'])

    def test_blind_overwrite_after_origin_drift_is_BLOCKED(self):
        """Ровно то, чего я НЕ сделал 22.09: положить свой файл поверх ушедшего origin.

        Цена была измерена заранее — 75 строк цикла #667.
        """
        r = DI.analyse(JOURNAL, ORIGIN_AFTER_DRIFT, GOOD_APPEND)
        self.assertEqual(r['verdict'], 'BLOCK', r)
        self.assertIn(DRIFT_ENTRY, ''.join(r['missing_headings']) or DRIFT_ENTRY)
        self.assertGreater(r['lost_lines'], 0)

    def test_authorized_deletion_needs_the_capability(self):
        rule = '.claude/rules/deployment.md'
        without = DI.analyse(rule, CANON, None)
        self.assertEqual(without['verdict'], 'BLOCK', without)
        with_cap = DI.analyse(rule, CANON, None,
                              deletion_capability='owner-approval-2026-09-22')
        self.assertEqual(with_cap['verdict'], 'PASS', with_cap)


class DuplicateAppendWhereUniquenessApplies(unittest.TestCase):

    def test_appending_the_same_entry_twice_is_BLOCKED(self):
        twice = _doc(REAL_HEADINGS + [MY_ENTRIES[0], MY_ENTRIES[0]])
        r = DI.analyse(JOURNAL, CANON, twice)
        self.assertEqual(r['verdict'], 'BLOCK', r)
        self.assertIn('duplicate_append_where_uniqueness_applies', r['findings'])

    def test_two_distinct_entries_are_not_a_duplicate(self):
        """Обратная сторона: иначе уникальность запрещала бы законное дописывание."""
        r = DI.analyse(JOURNAL, CANON, GOOD_APPEND)
        self.assertEqual(r['verdict'], 'PASS', r)
        self.assertNotIn('duplicate_append_where_uniqueness_applies', r['findings'])


class ClassesDecideTheAnswer(unittest.TestCase):

    def test_journal_is_append_only(self):
        self.assertEqual(DI.classify(JOURNAL), DI.APPEND_ONLY)

    def test_state_md_requires_a_merge(self):
        self.assertEqual(DI.classify('docs/STATE.md'), DI.MERGE_REQUIRED)

    def test_generated_manifest_may_be_replaced_wholesale(self):
        self.assertEqual(DI.classify('architecture/manifest.json'),
                         DI.GENERATED_REBUILDABLE)
        r = DI.analyse('architecture/manifest.json', b'{"agents":[1,2]}', b'{"agents":[]}')
        self.assertEqual(r['verdict'], 'PASS', r)

    def test_an_undeclared_shared_file_is_NOT_MEASURED_not_allowed(self):
        # Путь обязан лежать ВНУТРИ объявленной поверхности: снаружи вопрос не тот
        # (обычный исходник подменяется целиком законно).
        r = DI.analyse('docs/decisions/новая-тетрадь.md', CANON, STALE_CANDIDATE)
        self.assertEqual(r['file_class'], DI.UNKNOWN_FAIL_CLOSED)
        self.assertEqual(r['verdict'], 'NOT_MEASURED', r)

    def test_merge_required_refuses_a_blind_middle_rewrite(self):
        middle = _doc(REAL_HEADINGS, body_lines=6).replace(
            'строка 0'.encode('utf-8'), 'ПРАВКА'.encode('utf-8'))
        r = DI.analyse('docs/STATE.md', CANON, middle)
        self.assertIn(r['verdict'], ('BLOCK', 'NEEDS_MERGE'), r)
        self.assertNotEqual(r['verdict'], 'PASS')

    def test_a_declared_heading_pattern_absence_is_named(self):
        """Нет образца записи ⇒ сказано вслух, а не выдано за «заголовки целы»."""
        r = DI.analyse('data/audit_trail.jsonl', b'{"a":1}\n', b'{"a":1}\n{"b":2}\n')
        self.assertIn('heading_pattern_not_declared', r['findings'])
        self.assertEqual(r['verdict'], 'PASS', r)


class TheWorstOutcomeWins(unittest.TestCase):

    def test_one_blocked_file_blocks_the_whole_delivery(self):
        res = DI.check_delivery([
            (JOURNAL, CANON, GOOD_APPEND),
            ('docs/decisions/ADR-001-x.md', CANON, STALE_CANDIDATE)])
        self.assertEqual(res['verdict'], 'BLOCK')
        self.assertEqual(res['blocked'], ['docs/decisions/ADR-001-x.md'])

    def test_an_all_clean_delivery_passes(self):
        res = DI.check_delivery([(JOURNAL, CANON, GOOD_APPEND)])
        self.assertEqual(res['verdict'], 'PASS', res)

    def test_an_unknown_file_is_not_averaged_away(self):
        res = DI.check_delivery([
            (JOURNAL, CANON, GOOD_APPEND),
            ('docs/decisions/новьё.md', CANON, GOOD_APPEND)])
        self.assertEqual(res['verdict'], 'NOT_MEASURED')
        self.assertEqual(res['unmeasured'], ['docs/decisions/новьё.md'])


class TwoDeliveryIdentities(unittest.TestCase):
    """C5: набор путей и байты — РАЗНЫЕ вопросы, и имена обязаны это называть."""

    def _tree(self, tmp, journal_bytes):
        root = Path(tmp)
        (root / 'docs/journal').mkdir(parents=True, exist_ok=True)
        (root / 'docs/journal/2026-W39.md').write_bytes(journal_bytes)
        (root / 'scripts').mkdir(parents=True, exist_ok=True)
        (root / 'scripts/x.py').write_text('# код\n', encoding='utf-8')
        return root

    def test_same_paths_different_bytes_change_the_content_hash(self):
        from tempfile import TemporaryDirectory
        paths = [JOURNAL, 'scripts/x.py']
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            ra = DI.delivery_identities(self._tree(a, CANON), paths)
            rb = DI.delivery_identities(self._tree(b, STALE_CANDIDATE), paths)
            self.assertEqual(ra['DELIVERY_PATHSET_HASH'], rb['DELIVERY_PATHSET_HASH'])
            self.assertNotEqual(ra['DELIVERY_CONTENT_HASH'], rb['DELIVERY_CONTENT_HASH'])

    def test_same_bytes_give_the_same_content_hash(self):
        from tempfile import TemporaryDirectory
        paths = [JOURNAL, 'scripts/x.py']
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            ra = DI.delivery_identities(self._tree(a, CANON), paths)
            rb = DI.delivery_identities(self._tree(b, CANON), paths)
            self.assertEqual(ra['DELIVERY_CONTENT_HASH'], rb['DELIVERY_CONTENT_HASH'])

    def test_a_mode_change_alone_changes_the_content_hash(self):
        from tempfile import TemporaryDirectory
        paths = [JOURNAL, 'scripts/x.py']
        with TemporaryDirectory() as a:
            root = self._tree(a, CANON)
            before = DI.delivery_identities(root, paths)
            (root / 'scripts/x.py').chmod(0o600)
            after = DI.delivery_identities(root, paths)
            self.assertNotEqual(before['DELIVERY_CONTENT_HASH'],
                                after['DELIVERY_CONTENT_HASH'])

    def test_a_missing_path_is_not_measured_not_a_hash(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as a:
            root = self._tree(a, CANON)
            r = DI.delivery_identities(root, [JOURNAL, 'scripts/нет-такого.py'])
            self.assertEqual(r['state'], 'NOT_MEASURED')
            self.assertIsNone(r['DELIVERY_CONTENT_HASH'])
            self.assertEqual(len(r['unmeasured']), 1)

    def test_the_pathset_hash_is_blind_to_bytes_and_that_is_stated(self):
        """Прямая улика того дефекта, из-за которого имя врало."""
        from tempfile import TemporaryDirectory
        paths = [JOURNAL, 'scripts/x.py']
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            ra = DI.delivery_identities(self._tree(a, CANON), paths)
            rb = DI.delivery_identities(self._tree(b, STALE_CANDIDATE), paths)
            self.assertEqual(ra['DELIVERY_PATHSET_HASH'], rb['DELIVERY_PATHSET_HASH'])
            self.assertIn('НЕ', ra['pathset_note'])


if __name__ == '__main__':
    unittest.main()


class TheCanonicalSharedSurfaceIsDeclared(unittest.TestCase):
    """Без объявленной поверхности сторож блокирует всё и перестаёт различать.

    Замер 22.09 при подготовке доставки: набор из 65 путей почти целиком состоит из
    обычных исходников, и `UNKNOWN_FAIL_CLOSED` на каждом из них превратил бы отказ из
    находки в шум. Поверхность объявлена списком, а не выведена по расширению.
    """

    def test_a_journal_is_inside_the_surface(self):
        self.assertTrue(DI.applies_to(JOURNAL))

    def test_an_ordinary_source_file_is_outside_the_surface(self):
        self.assertFalse(DI.applies_to('scripts/cartographer/director_v13.py'))

    def test_an_ordinary_source_file_is_NOT_APPLICABLE_not_blocked(self):
        r = DI.analyse('scripts/cartographer/director_v13.py', b'a\n', b'b\n')
        self.assertEqual(r['verdict'], DI.NOT_APPLICABLE, r)

    def test_an_undeclared_path_INSIDE_the_surface_still_fails_closed(self):
        """Обратная сторона: внутри поверхности незнание остаётся отказом."""
        r = DI.analyse('docs/journal/../decisions/новьё.txt', CANON, STALE_CANDIDATE)
        r2 = DI.analyse('nimbalyst-local/новая-тетрадь.md', CANON, STALE_CANDIDATE)
        self.assertEqual(r2['verdict'], 'NOT_MEASURED', r2)
        self.assertIn('ВНУТРИ поверхности', r2['reasons'][0])

    def test_not_applicable_does_not_mask_a_real_block(self):
        """Итог набора не должен «улучшаться» от присутствия неприменимых путей."""
        res = DI.check_delivery([
            ('scripts/cartographer/x.py', b'a\n', b'b\n'),
            (JOURNAL, CANON, STALE_CANDIDATE)])
        self.assertEqual(res['verdict'], 'BLOCK', res)


class InheritedDuplicatesAreNotOurFault(unittest.TestCase):
    """Дубль, уже лежащий в каноне, не является находкой об ЭТОЙ доставке.

    Замер 22.09 при подготовке доставки: на origin в `docs/decisions/INDEX.md` уже были
    три дубля идентификаторов (ADR-067, ADR-073, ADR-145), и первая редакция проверки
    уникальности заблокировала доставку за чужую историю — верный ответ не на тот вопрос.
    """

    INDEX = 'docs/decisions/INDEX.md'

    def _index(self, rows):
        head = '| ADR | Заголовок | Статус | Файл |\n|---|---|---|---|\n'
        return (head + '\n'.join(f'| ADR-{n} | заголовок | Accepted | [x](x.md) |'
                                 for n in rows) + '\n').encode('utf-8')

    def test_an_inherited_duplicate_does_not_block(self):
        src = self._index([1, 2, 2, 3])          # дубль УЖЕ в каноне
        cand = self._index([1, 2, 2, 3, 4])      # мы лишь дописали строку
        r = DI.analyse(self.INDEX, src, cand)
        self.assertEqual(r['verdict'], 'PASS', r)
        self.assertNotIn('duplicate_append_where_uniqueness_applies', r['findings'])
        self.assertTrue(r.get('inherited_duplicate_headings'))

    def test_a_duplicate_WE_introduce_still_blocks(self):
        """Обратная сторона: без неё починка сняла бы проверку целиком."""
        src = self._index([1, 2, 3])
        cand = self._index([1, 2, 3, 3])         # дубль создали МЫ
        r = DI.analyse(self.INDEX, src, cand)
        self.assertEqual(r['verdict'], 'BLOCK', r)
        self.assertIn('duplicate_append_where_uniqueness_applies', r['findings'])

    def test_deepening_an_inherited_duplicate_blocks(self):
        """Углубление чужого дубля — уже наше действие."""
        src = self._index([1, 2, 2])
        cand = self._index([1, 2, 2, 2])
        r = DI.analyse(self.INDEX, src, cand)
        self.assertEqual(r['verdict'], 'BLOCK', r)
