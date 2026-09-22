#!/usr/bin/env python3
"""Целостность доставки общих канонических файлов (ТЕНЕВОЕ, не проведено).

Авария, из которой написан модуль (22.09)
=========================================
Кандидат выпуска прошёл полный CI — ``candidate_only = 0``, ``NEW_REGRESSION = 0``,
``PROMOTION_CRITICAL_FAILURES = 0`` — и при этом несли в себе УСТАРЕВШУЮ копию
дописываемого журнала: 40 383 байта, 349 строк, **пять целых канонических записей**
(циклы #661, #662, #665, #666 и R&D-итерация заказа #110) были уничтожены. Ни один тест
этого не сказал; нашлось разбором дрейфа вручную.

Сторож потери записей СУЩЕСТВУЕТ (``push_to_github.py``: ``guard_entry_loss`` /
``guard_content_loss`` / ``classify_missing_entries``) и работает fail-CLOSED — но стоит у
двери **пуша**. Между «собрал дерево» и «запушил» лежит операция подмены файла целиком, у
которой сторожа нет вовсе, и регрессионная улика CI на неё слепа по построению.

Вторая измеренная граница существующего сторожа, названная им самим
(``push_to_github.py:949``): он ловит исчезновение **ЗАГОЛОВКА** записи и НЕ ловит удаление
её **ТЕЛА**. Улика: ``a3c015f05`` снёс 1729 строк ``docs/STATE.md``, не тронув ни одного
заголовка, и остался невидимым. Поэтому здесь мера — СОДЕРЖИМОЕ, а не заголовки и не
набор путей.

Чего модуль НЕ делает
=====================
Не пушит, не мержит, не правит канонические документы, не включается в живые расписания.
Отвечает только на вопрос «переживёт ли канон эту доставку» и отказывает, когда не знает.
LLM запрещён. Только stdlib.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
from pathlib import Path

# ── C2. Семантика канонических файлов: ОБЪЯВЛЕНА, а не выведена по расширению ────────
IMMUTABLE_REPLACE_OK = 'IMMUTABLE_REPLACE_OK'
GENERATED_REBUILDABLE = 'GENERATED_REBUILDABLE'
APPEND_ONLY = 'APPEND_ONLY'
MERGE_REQUIRED = 'MERGE_REQUIRED'
DELETE_OWNER_APPROVAL = 'DELETE_OWNER_APPROVAL'
UNKNOWN_FAIL_CLOSED = 'UNKNOWN_FAIL_CLOSED'

#: Порядок значим: первое совпадение решает. Классифицировать весь репозиторий руками
#: запрещено (это была бы база ложных срабатываний, которую научатся дописывать);
#: объявлены ИЗВЕСТНЫЕ общие канонические семьи, всё прочее — третий исход.
POLICY = (
    ('docs/journal/*.md',                 APPEND_ONLY),
    ('docs/decisions/ADR-*.md',           APPEND_ONLY),
    ('docs/adr/ADR-*.md',                 APPEND_ONLY),
    ('docs/decisions/INDEX.md',           APPEND_ONLY),
    ('docs/STATE.md',                     MERGE_REQUIRED),
    ('nimbalyst-local/tracker/_BOARD.md', GENERATED_REBUILDABLE),
    ('nimbalyst-local/tracker/own-*.md',  MERGE_REQUIRED),
    ('nimbalyst-local/tracker/owner-decision-*.md', MERGE_REQUIRED),
    ('nimbalyst-local/tracker/inbox-*.md', MERGE_REQUIRED),
    ('nimbalyst-local/tracker/agent-*.md', MERGE_REQUIRED),
    ('data/audit_trail.jsonl',            APPEND_ONLY),
    ('.claude/rules/*.md',                MERGE_REQUIRED),
    ('CLAUDE.md',                         MERGE_REQUIRED),
    ('architecture/manifest.json',        GENERATED_REBUILDABLE),
    ('architecture/*.json',               GENERATED_REBUILDABLE),
    ('landing/src/data/*.json',           GENERATED_REBUILDABLE),
    ('landing/src/lib/constitution.json', GENERATED_REBUILDABLE),
)

#: Семьи, у которых заголовок записи уникален: два одинаковых заголовка — дефект
#: дописывания, а не «стало больше». Замер ADR-395: «другой прогон того же дня ОСТАЁТСЯ»,
#: поэтому уникальность объявляется ПОИМЁННО, а не распространяется на все APPEND_ONLY.
UNIQUE_HEADING_FAMILIES = ('docs/journal/*.md', 'docs/decisions/INDEX.md')

#: Как выглядит «запись» в каждой семье. Отсутствие образца ⇒ проверка заголовков НЕ
#: выполняется и это НАЗЫВАЕТСЯ, а не выдаётся за «заголовки целы».
HEADING_PATTERNS = (
    ('docs/journal/*.md', r'^##\s+.+$'),
    ('docs/decisions/INDEX.md', r'^\|\s*ADR-\d+', ),
    ('docs/STATE.md', r'^##\s+.+$'),
    ('.claude/rules/*.md', r'^##\s+.+$'),
    ('CLAUDE.md', r'^##\s+.+$'),
)

#: ПОВЕРХНОСТЬ общих канонических документов — объявлена, потому что без неё сторож
#: отвечает не на свой вопрос. Обычный исходник (`scripts/cartographer/*.py`) не является
#: общей дописываемой тетрадью: у него один владелец — доставка, и подмена его целиком
#: законна. Если не объявить поверхность, каждый такой файл попадёт в
#: `UNKNOWN_FAIL_CLOSED` и сторож заблокирует всё, то есть перестанет различать.
#: Внутри поверхности необъявленный путь — ОТКАЗ; вне поверхности — `NOT_APPLICABLE`.
CANONICAL_SHARED_SURFACE = (
    'docs/journal/', 'docs/decisions/', 'docs/adr/', 'docs/STATE.md',
    'nimbalyst-local/', '.claude/rules/', 'CLAUDE.md', 'data/audit_trail.jsonl',
)

#: ГРАНИЦА ПОВЕРХНОСТИ, названная вслух. `docs/` целиком в неё НЕ входит: отчёты вида
#: `docs/audits/*.md` и нумерованные `docs/NN_*.md` пишет один автор за раз, и подмена их
#: целиком законна. Внутри — только семьи, которые дописывают РАЗНЫЕ писатели и чья
#: история служит уликой. Расширять поверхность — решение (ADR), а не правка строки:
#: каждое добавление превращает законную подмену в отказ, и наоборот.

NOT_APPLICABLE = 'NOT_APPLICABLE'


def applies_to(path: str) -> bool:
    """Является ли путь общим каноническим документом. Решает ОБЪЯВЛЕНИЕ, не расширение."""
    rel = str(path).lstrip('./')
    return any(rel == s or rel.startswith(s) for s in CANONICAL_SHARED_SURFACE)


#: Класс файлов, у которых доставка НИКОГДА не считается безопасной автономно.
NEVER_AUTONOMOUS = (MERGE_REQUIRED, DELETE_OWNER_APPROVAL, UNKNOWN_FAIL_CLOSED)


def classify(path: str) -> str:
    """Класс общего канонического файла. Не объявлен ⇒ ``UNKNOWN_FAIL_CLOSED``."""
    rel = str(path).lstrip('./')
    for pattern, cls in POLICY:
        if fnmatch.fnmatch(rel, pattern):
            return cls
    return UNKNOWN_FAIL_CLOSED


def _heading_pattern(path: str):
    rel = str(path).lstrip('./')
    for pattern, rx in HEADING_PATTERNS:
        if fnmatch.fnmatch(rel, pattern):
            return re.compile(rx, re.M)
    return None


def _unique_headings(path: str) -> bool:
    rel = str(path).lstrip('./')
    return any(fnmatch.fnmatch(rel, p) for p in UNIQUE_HEADING_FAMILIES)


# ── C5. Две идентичности доставки, и они отвечают на РАЗНЫЕ вопросы ──────────────────
def _file_rows(root, paths):
    """(путь, режим, sha содержимого). Непрочитанный путь ⇒ строка с ``None``."""
    rows, unmeasured = [], []
    for rel in sorted(paths):
        f = Path(root) / rel
        if not f.exists():
            unmeasured.append((rel, 'путь отсутствует'))
            continue
        try:
            blob = f.read_bytes()
            mode = oct(os.stat(f).st_mode & 0o777)
        except OSError as exc:
            unmeasured.append((rel, f'не прочитан: {exc.strerror}'))
            continue
        rows.append((rel, mode, hashlib.sha256(blob).hexdigest()))
    return rows, unmeasured


def delivery_identities(root, paths):
    """``DELIVERY_PATHSET_HASH`` (сведения) и ``DELIVERY_CONTENT_HASH`` (решение).

    Инвариант: те же пути + другие байты ⇒ РАЗНЫЙ content-хеш; те же байты ⇒ тот же.
    Режим входит в content-хеш: права — часть доставки
    (``.claude/rules/deployment.md`` п. 3; режим 100644 у обёртки launchd = мёртвый агент).
    Непрочитанный путь ⇒ **НЕ ИЗМЕРЕНО**, а не хеш и не «чисто» (инв. #17).
    """
    rows, unmeasured = _file_rows(root, paths)
    ph = hashlib.sha256()
    for rel, _, _ in rows:
        ph.update(rel.encode()); ph.update(b'\n')
    ch = hashlib.sha256()
    for rel, mode, sha in rows:
        ch.update(rel.encode()); ch.update(b'\0')
        ch.update(mode.encode()); ch.update(b'\0')
        ch.update(sha.encode()); ch.update(b'\n')
    return {
        'files': len(rows),
        'DELIVERY_PATHSET_HASH': ph.hexdigest(),
        'DELIVERY_CONTENT_HASH': None if unmeasured else ch.hexdigest(),
        'unmeasured': unmeasured,
        'state': 'NOT_MEASURED' if unmeasured else 'MEASURED',
        'pathset_note': 'сведения: отвечает «какие пути», НЕ «какие байты»',
        'content_note': 'решение: путь + режим + sha содержимого каждого файла',
    }


# ── C3. Сторож сохранности содержимого ──────────────────────────────────────────────
def _lines(blob: bytes):
    return blob.decode('utf-8', errors='replace').splitlines()


def analyse(path, source: bytes, candidate: bytes, *,
            deletion_capability=None):
    """Переживёт ли канон эту доставку. Мера — СОДЕРЖИМОЕ.

    ``source`` — канон, поверх которого доставляем (версия origin/базы).
    ``candidate`` — что мы собираемся положить. ``None`` означает удаление файла.
    """
    cls = classify(path)
    out = {'path': str(path), 'file_class': cls, 'verdict': None, 'reasons': [],
           'findings': []}

    if candidate is None:
        if cls == DELETE_OWNER_APPROVAL or cls in NEVER_AUTONOMOUS:
            ok = bool(deletion_capability)
            out['verdict'] = 'PASS' if ok else 'BLOCK'
            out['reasons'].append('удаление требует явного полномочия владельца'
                                  if not ok else
                                  f'удаление разрешено полномочием {deletion_capability!r}')
            return out
        out['verdict'] = 'PASS'
        out['reasons'].append('класс допускает удаление без отдельного полномочия')
        return out

    if cls == UNKNOWN_FAIL_CLOSED:
        if not applies_to(path):
            out['verdict'] = NOT_APPLICABLE
            out['file_class'] = NOT_APPLICABLE
            out['reasons'].append('путь вне поверхности общих канонических документов: '
                                  'обычный исходник, у него один владелец — доставка')
            return out
        out['verdict'] = 'NOT_MEASURED'
        out['reasons'].append('путь ВНУТРИ поверхности общих канонических документов, но '
                              'класс НЕ ОБЪЯВЛЕН: для автономной доставки это отказ, '
                              'а не разрешение')
        return out

    if cls == GENERATED_REBUILDABLE:
        out['verdict'] = 'PASS'
        out['reasons'].append('генерируемый артефакт: подмена целиком законна, '
                              'источник правды — генератор')
        return out

    if cls == IMMUTABLE_REPLACE_OK:
        out['verdict'] = 'PASS'
        out['reasons'].append('класс допускает замену целиком')
        return out

    # Ниже — APPEND_ONLY и MERGE_REQUIRED: обе требуют сохранности содержимого.
    src_lines, cand_lines = _lines(source), _lines(candidate)
    cand_set = set(cand_lines)
    lost = [l for l in src_lines if l.strip() and l not in cand_set]
    out['source_bytes'], out['candidate_bytes'] = len(source), len(candidate)
    out['source_lines'], out['candidate_lines'] = len(src_lines), len(cand_lines)
    out['lost_lines'] = len(lost)
    out['lost_sample'] = [l[:120] for l in lost[:5]]
    out['exact_byte_prefix'] = candidate[:len(source)] == source

    rx = _heading_pattern(path)
    if rx is None:
        # Находки — МАШИННЫЕ токены; проза живёт в reasons. Смешать их значило бы
        # заставить каждого потребителя сверяться подстрокой.
        out['findings'].append('heading_pattern_not_declared')
        out['reasons'].append('образец записи для этой семьи не объявлен ⇒ проверка '
                              'заголовков НЕ выполнялась; это НАЗВАНО, а не выдано за '
                              'целость заголовков')
        src_head, cand_head = [], []
    else:
        src_head = rx.findall(source.decode('utf-8', errors='replace'))
        cand_head = rx.findall(candidate.decode('utf-8', errors='replace'))
    out['source_headings'], out['candidate_headings'] = len(src_head), len(cand_head)
    missing_head = [h for h in src_head if h not in cand_head]
    out['missing_headings'] = missing_head[:5]

    # Находки — по КЛАССАМ дефектов, которые требовал назвать ARB.
    if missing_head:
        out['findings'].append('missing_section')
    if lost and not missing_head and rx is not None:
        # заголовки целы, а строки исчезли — ровно форма a3c015f05
        out['findings'].append('body_deletion_under_surviving_heading')
    if lost:
        out['findings'].append('silent_line_loss')
    if len(candidate) < len(source) and not lost:
        out['findings'].append('shrank_without_line_loss')
    if len(candidate) < len(source) and lost:
        out['findings'].append('truncation')
    if not out['exact_byte_prefix'] and not lost and len(candidate) > len(source):
        out['findings'].append('content_preserved_but_not_pure_append')
    if _unique_headings(path):
        # Вопрос — «создала ли дубль ЭТА доставка», а не «есть ли дубли вообще».
        # Замер 22.09: на origin уже лежали три дубля идентификаторов реестра
        # (ADR-067, ADR-073, ADR-145), и первая редакция этой проверки заблокировала
        # доставку за чужую историю. Дубль канона — не находка о нас.
        from collections import Counter
        src_n, cand_n = Counter(src_head), Counter(cand_head)
        dup = sorted(h for h, n in cand_n.items()
                     if n > 1 and n > src_n.get(h, 0))
        inherited = sorted(h for h, n in src_n.items() if n > 1)
        if inherited:
            out['inherited_duplicate_headings'] = inherited[:5]
            out['reasons'].append(f'дублей заголовков УНАСЛЕДОВАНО от канона: '
                                  f'{len(inherited)} — доставке не приписываются')
        if dup:
            out['findings'].append('duplicate_append_where_uniqueness_applies')
            out['duplicate_headings'] = dup[:5]

    if cls == APPEND_ONLY:
        if lost or missing_head:
            out['verdict'] = 'BLOCK'
            out['reasons'].append(f'APPEND_ONLY: потеряно строк {len(lost)}, '
                                  f'исчезло заголовков {len(missing_head)}')
        elif 'duplicate_append_where_uniqueness_applies' in out['findings']:
            out['verdict'] = 'BLOCK'
            out['reasons'].append('APPEND_ONLY с уникальными заголовками: запись '
                                  'дописана дважды')
        else:
            out['verdict'] = 'PASS'
            out['reasons'].append('весь канон пережил доставку' +
                                  (' (чистое дописывание)' if out['exact_byte_prefix']
                                   else ' (правка середины, содержимое цело)'))
        return out

    # MERGE_REQUIRED: слепая подмена целиком запрещена даже без потерь.
    if out['exact_byte_prefix']:
        out['verdict'] = 'PASS'
        out['reasons'].append('MERGE_REQUIRED: доставка есть дописывание поверх канона')
    elif lost or missing_head:
        out['verdict'] = 'BLOCK'
        out['reasons'].append(f'MERGE_REQUIRED: слепая подмена, потеряно строк {len(lost)}')
    else:
        out['verdict'] = 'NEEDS_MERGE'
        out['reasons'].append('MERGE_REQUIRED: середина изменена без потерь — требуется '
                              'объявленное слияние, а не подмена целиком')
    return out


def check_delivery(pairs, *, deletion_capability=None):
    """Набор доставок. Итог — худший исход, и он НАЗВАН, а не усреднён."""
    rows = [analyse(p, s, c, deletion_capability=deletion_capability)
            for p, s, c in pairs]
    order = {'BLOCK': 0, 'NOT_MEASURED': 1, 'NEEDS_MERGE': 2, 'PASS': 3,
             NOT_APPLICABLE: 4}
    worst = min((r['verdict'] for r in rows), key=lambda v: order.get(v, 0),
                default='PASS')
    return {'rows': rows, 'verdict': worst,
            'blocked': [r['path'] for r in rows if r['verdict'] == 'BLOCK'],
            'unmeasured': [r['path'] for r in rows if r['verdict'] == 'NOT_MEASURED'],
            'needs_merge': [r['path'] for r in rows if r['verdict'] == 'NEEDS_MERGE'],
            'note': ('зелёная регрессия CI не есть улика безопасности доставки: это два '
                     'разных вопроса, и на втором сторожа у двери сборки не было')}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--path', required=True, help='канонический путь внутри репозитория')
    ap.add_argument('--source', required=True, help='файл с версией КАНОНА')
    ap.add_argument('--candidate', help='файл с версией КАНДИДАТА; опустить = удаление')
    ap.add_argument('--deletion-capability')
    ap.add_argument('--json')
    ns = ap.parse_args(argv)
    src = Path(ns.source).read_bytes()
    cand = Path(ns.candidate).read_bytes() if ns.candidate else None
    row = analyse(ns.path, src, cand, deletion_capability=ns.deletion_capability)
    print(json.dumps(row, ensure_ascii=False, indent=1))
    return {'PASS': 0, 'NEEDS_MERGE': 3, 'NOT_MEASURED': 2}.get(row['verdict'], 1)


if __name__ == '__main__':
    raise SystemExit(main())
