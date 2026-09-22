#!/usr/bin/env python3
"""Улика выпуска Director OS v1 (Phase 9) — что именно выходит и чего оно НЕ умеет.

Манифест ПРОИЗВОДНЫЙ. Он не источник правды и не реестр: он пересобирается из принятых
снимков и из дерева, и его единственная задача — чтобы утверждение «v1 выпущен» можно было
проверить, не веря на слово.

Честность манифеста держится на трёх вещах: он называет базовый коммит, перечисляет
ОГРАНИЧЕНИЯ и незакрытые пробелы наравне с достижениями, и объявляет запрещённые действия
списком, а не умолчанием.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import diff as diff_mod  # noqa: E402
import reliability as reliability_mod  # noqa: E402

SCHEMA = 'cartographer.v1_release_manifest/0.1'

# Дорожная карта — ДЕСЯТЬ номерных фаз, 0…9. Внутри нулевой было три подфазы (0A, 0B,
# 0C) — это подробность реализации, а не одиннадцатая фаза. Называть их «11 фазами» без
# пояснения значило бы завести два разных счёта одного и того же.
ROADMAP_PHASE_RANGE = '0-9'
ROADMAP_PHASE_COUNT = 10
IMPLEMENTATION_SUBPHASES = ('0A', '0B', '0C')

PHASES = (
    ('0A/0B', 'Cartographer: наблюдение машины и карта системы',
     ('snapshot.py', 'system_map.py')),
    ('0C', 'Сравнение снимков и карта родов фактов',
     ('diff.py', 'source_of_truth.py')),
    ('1', 'Сводка владельца', ('owner_briefing.py', 'render.py', 'brief.py')),
    ('2', 'Портал студии', ('portal_extract.py', 'portal_render.py', 'portal.py')),
    ('3', 'Источник правды и расхождения', ('authority_map.py',)),
    ('4', 'Надёжность и проблемы', ('reliability.py',)),
    ('5', 'Разработка и работа', ('work.py',)),
    ('6', 'Центр директора', ('director.py',)),
    ('7', 'Инвестиции и R&D', ('investments.py',)),
    ('8', 'Управление и восстановление', ('governance.py',)),
    ('9', 'Действия и границы v1', ('actions.py', 'release.py')),
)

LAYERS = (
    ('snapshot.json', 'cartographer.snapshot/0.3'),
    ('authority_map.json', 'cartographer.authority_map/0.1'),
    ('reliability_snapshot.json', 'cartographer.reliability_snapshot/0.1'),
    ('work_snapshot.json', 'cartographer.work_snapshot/0.1'),
    ('director_center.json', 'cartographer.director_center/0.1'),
    ('investment_snapshot.json', 'cartographer.investment_snapshot/0.1'),
    ('governance_snapshot.json', 'cartographer.governance_snapshot/0.1'),
    ('action_authority_audit.json', 'cartographer.action_authority_audit/0.1'),
)


class ReleaseInputError(Exception):
    """Вход не соответствует контракту. Отказ, а не молчаливая догадка."""


def _now():
    return dt.datetime.now(dt.timezone.utc)


#: Обёртки launchd, входящие в население выпуска Director. Решают, КАКОЙ путь кода
#: исполняется, поэтому идентичность выпуска без них неполна (замер 22.09).
WRAPPERS = ('scripts/agent_director_build.sh', 'scripts/agent_director_server.sh')


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def build_release_manifest(production, bundle, base_sha, *, tests=None,
                           browser=None, performance=None, now=None,
                           cartographer=None, major=None, pages=None):
    """Манифест выпуска. Всё, что не измерено, остаётся пустым и НАЗЫВАЕТСЯ пустым."""
    now = now or _now()
    production, bundle = Path(production), Path(bundle)

    files = []
    root = production / 'scripts/cartographer'
    for p in sorted(root.glob('*.py')):
        files.append({'path': f'scripts/cartographer/{p.name}',
                      'sha256': _sha256(p), 'size_bytes': p.stat().st_size})
    troot = production / 'tests/cartographer'
    for p in sorted(troot.glob('*.py')) if troot.is_dir() else []:
        files.append({'path': f'tests/cartographer/{p.name}',
                      'sha256': _sha256(p), 'size_bytes': p.stat().st_size})
    # Обёртки launchd — ЧАСТЬ ВЫПУСКА, а не окружения: они выбирают исполняемый путь.
    # Замер 22.09 (v1.3.1): весь код v1.3 лежал в прод-дереве, приёмка была зелёной,
    # /health отвечал ok — и владелец видел путь v1.2, потому что обёртка сборки не
    # передавала --v13. Идентичность выпуска, не включающая обёртку, не различает
    # «v1.3 исполняется» и «v1.3 лежит рядом». Режим файла включён по той же причине,
    # по которой он часть доставки: 100644 у обёртки launchd = мёртвый агент.
    wrappers_missing = []
    for name in WRAPPERS:
        w = production / name
        if w.exists():
            files.append({'path': name, 'sha256': _sha256(w),
                          'size_bytes': w.stat().st_size,
                          'mode': oct(w.stat().st_mode & 0o777),
                          'role': 'launchd_wrapper_selects_runtime_path'})
        else:
            # Третий исход живёт СВОИМ полем, а не строкой в ``files``. Контракт
            # ``files`` тотален: каждая перечисленная строка несёт настоящий sha256
            # (``test_the_manifest_lists_the_files_it_claims``). Положить туда None
            # значило бы сломать контракт, чтобы отчитаться об отсутствии — то есть
            # починить одно, сломав другое. Отсутствие НАЗВАНО, но не подделано.
            wrappers_missing.append(name)

    layers, limitations, gaps, conditions = [], [], [], []
    prohibited, ready_actions = [], []
    for name, schema in LAYERS:
        # снимок наблюдения машины лежит в СВОЁМ комплекте, а не рядом со страницей:
        # искать его в комплекте портала значило бы отчитаться о ложном отсутствии
        p = ((Path(cartographer) / name) if (cartographer and name == 'snapshot.json')
             else bundle / name)
        doc, state = reliability_mod._read_json(p)
        rec = {'layer': name, 'status': state,
               'schema': (doc or {}).get('schema_version') if isinstance(doc, dict)
               else None,
               'schema_expected': schema,
               'digest': (doc or {}).get('semantic_digest') if isinstance(doc, dict)
               else None,
               'generated_at': (doc or {}).get('generated_at') if isinstance(doc, dict)
               else None}
        if isinstance(doc, dict):
            limitations.extend({'layer': name, 'limit': x}
                               for x in (doc.get('limits') or []))
            if name == 'governance_snapshot.json':
                gaps = [{'id': i['governance_id'], 'title': i['title']}
                        for i in doc.get('items') or [] if i.get('category') == 'gap']
            if name == 'reliability_snapshot.json':
                c = doc.get('counts') or {}
                conditions = [
                    {'name': 'подтверждено сейчас', 'value': c.get('active_confirmed')},
                    {'name': 'требует перепроверки', 'value': c.get('active_unverified')},
                    {'name': 'CRITICAL подтверждённых',
                     'value': c.get('critical_confirmed_now')},
                ]
            if name == 'action_authority_audit.json':
                prohibited = list(doc.get('red_zone') or [])
                ready_actions = [a['action'] for a in doc.get('actions') or []
                                 if a.get('verdict') == 'READY_FOR_UI']
        layers.append(rec)

    manifest = {
        'schema_version': SCHEMA,
        'generated_at': now.isoformat(),
        'derived_evidence': True,
        'is_not_a_source_of_truth':
            'манифест описывает, ЧТО выпущено и чего оно не умеет; состав пересчитывается '
            'из дерева и снимков в любой момент',
        'base_origin_sha': base_sha,
        'production': str(production),
        'bundle': str(bundle),
        'roadmap_phase_range': ROADMAP_PHASE_RANGE,
        'roadmap_phase_count': ROADMAP_PHASE_COUNT,
        'implementation_subphases': list(IMPLEMENTATION_SUBPHASES),
        'phase_entry_count': len(PHASES),
        'phase_count_note':
            f'номерных фаз {ROADMAP_PHASE_COUNT} (диапазон {ROADMAP_PHASE_RANGE}); '
            f'записей ниже {len(PHASES)}, потому что нулевая фаза разложена на подфазы '
            f'{", ".join(IMPLEMENTATION_SUBPHASES)} — это подробность реализации, а не '
            'лишняя фаза',
        'phases': [{'phase': ph, 'title': title, 'modules': list(mods)}
                   for ph, title, mods in PHASES],
        'files': files,
        'file_count': len(files),
        # Объявленное население выпуска, которого в дереве НЕ НАШЛОСЬ. Пустой список =
        # измерено и равно нулю; непустой = выпуск неполон и это видно, а не утоплено
        # в общем числе файлов (инв. #17).
        'release_population_missing': wrappers_missing,
        'layers': layers,
        'pages': list(pages or ()),
        'page_count': len(pages or ()),
        'read_only': True,
        'action_capabilities': {
            'ready_for_ui': ready_actions,
            'count': len(ready_actions),
            'note': 'ноль готовых действий означает, что v1 выходит полностью read-only '
                    'и ни одной кнопки действия не показывает',
        },
        'prohibited_actions': prohibited,
        'known_limitations': limitations,
        'known_limitations_total': len(limitations),
        'known_limitations_note':
            'это ВСЕ границы, объявленные слоями поимённо. Отдельно ниже названы те, что '
            'меняют решение владельца о выпуске — человеческая сводка короче по построению',
        'major_release_limitations': list(major or ()),
        'major_release_limitations_count': len(major or ()),
        'unresolved_governance_gaps': gaps,
        'unresolved_reliability_conditions': conditions,
        'tests': tests or {'status': 'NOT_MEASURED'},
        'browser_acceptance': browser or {'status': 'NOT_MEASURED'},
        'performance': performance or {'status': 'NOT_MEASURED'},
        'evidence_timestamps': {
            'manifest_generated_at': now.isoformat(),
            'layers': {rec['layer']: rec['generated_at'] for rec in layers},
        },
    }
    manifest['semantic_digest'] = semantic_digest(manifest)
    return manifest


def semantic_view(manifest):
    return {k: v for k, v in manifest.items()
            if k not in ('generated_at', 'semantic_digest', 'evidence_timestamps')}


def semantic_digest(manifest):
    payload = json.dumps(semantic_view(manifest), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]


def validate_release_manifest(manifest, where):
    def need(cond, message):
        if not cond:
            raise ReleaseInputError(f'{where}: {message}')

    need(isinstance(manifest, dict), 'манифест не является объектом')
    need(manifest.get('schema_version') == SCHEMA,
         f"схема {manifest.get('schema_version')!r}, ожидалась {SCHEMA!r}")
    for key in ('base_origin_sha', 'phases', 'files', 'layers', 'known_limitations',
                'unresolved_governance_gaps', 'prohibited_actions',
                'action_capabilities', 'tests', 'browser_acceptance', 'performance',
                'roadmap_phase_range', 'roadmap_phase_count',
                'known_limitations_total', 'major_release_limitations'):
        need(key in manifest, f'поле {key} отсутствует')
    need(manifest.get('derived_evidence') is True,
         'манифест обязан объявлять себя производной уликой')
    need(bool(manifest['base_origin_sha']) and len(manifest['base_origin_sha']) >= 12,
         'базовый коммит не назван')
    need(bool(manifest['prohibited_actions']), 'список запрещённых действий пуст')
    caps = manifest['action_capabilities']
    need(caps['count'] == len(caps['ready_for_ui']),
         'число готовых действий не сходится со списком')
    need(not (manifest.get('read_only') is True and caps['count'] > 0),
         'манифест объявляет выпуск read-only при наличии готовых действий')
    need(manifest['known_limitations_total'] == len(manifest['known_limitations']),
         'счёт ограничений не сходится с самим списком')
    need(manifest['major_release_limitations_count']
         == len(manifest['major_release_limitations']),
         'счёт главных ограничений не сходится со списком')
    need(manifest['major_release_limitations_count']
         <= manifest['known_limitations_total'],
         'главных ограничений больше, чем всех — счета расходятся')
    need(manifest['roadmap_phase_count'] == ROADMAP_PHASE_COUNT
         and manifest['roadmap_phase_range'] == ROADMAP_PHASE_RANGE,
         'дорожная карта объявлена не так, как считает модуль')
    need(bool(manifest.get('phase_count_note')),
         'расхождение между числом фаз и числом записей не объяснено')
    need(manifest['file_count'] == len(manifest['files']),
         'счёт файлов не сходится со списком')
    need(manifest['page_count'] == len(manifest['pages']),
         'счёт страниц не сходится со списком')
    for name in ('tests', 'browser_acceptance', 'performance'):
        block = manifest[name]
        need(isinstance(block, dict) and block,
             f'{name} обязан быть объектом; «не измерено» тоже объявляется явно')
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--production', type=Path, default=Path.home() / 'Documents/SPA_Claude')
    ap.add_argument('--bundle', type=Path, required=True,
                    help='каталог с принятыми снимками всех фаз')
    ap.add_argument('--base-sha', required=True)
    ap.add_argument('--cartographer', type=Path,
                    help='комплект Cartographer: там живёт snapshot.json')
    ap.add_argument('--tests', help='JSON с результатом прогона тестов')
    ap.add_argument('--browser', help='JSON с результатом браузерной приёмки')
    ap.add_argument('--performance', help='JSON с замером производительности')
    ap.add_argument('--major', help='JSON-список главных ограничений выпуска')
    ap.add_argument('--pages', help='JSON-список страниц с их замерами')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)

    final = Path(args.output)
    if final.exists():
        raise SystemExit(f'{final} уже существует; каждый прогон пишет новый каталог')
    load = lambda raw: (json.loads(raw) if raw else None)  # noqa: E731
    try:
        manifest = build_release_manifest(
            args.production, args.bundle, args.base_sha,
            tests=load(args.tests), browser=load(args.browser),
            performance=load(args.performance), cartographer=args.cartographer,
            major=load(args.major), pages=load(args.pages))
        validate_release_manifest(manifest, 'freshly built')
    except (ReleaseInputError, ValueError) as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nМанифест не построен.')

    protected = [Path(args.production), Path(args.bundle)]
    if args.cartographer:
        protected.append(Path(args.cartographer))
    diff_mod.validate_output(final, protected)
    staging = final.with_name(final.name + '.incomplete')
    if staging.exists():
        raise SystemExit(f'{staging} остался от прерванного прогона; отодвиньте его')
    staging.mkdir(parents=True, mode=0o700)
    p = staging / 'director_os_v1_release_manifest.json'
    with p.open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(manifest, indent=2, ensure_ascii=False,
                                allow_nan=False) + '\n')
    p.chmod(0o600)
    os.rename(staging, final)

    print(f"База: {manifest['base_origin_sha'][:12]} · фаз "
          f"{manifest['roadmap_phase_count']} ({manifest['roadmap_phase_range']}), "
          f"записей {manifest['phase_entry_count']} · страниц {manifest['page_count']} · "
          f"файлов {manifest['file_count']}")
    print(f"Слоёв прочитано: "
          f"{sum(1 for x in manifest['layers'] if x['status'] == 'READ')} из "
          f"{len(manifest['layers'])}")
    print(f"Готовых действий: {manifest['action_capabilities']['count']} · запрещённых: "
          f"{len(manifest['prohibited_actions'])} · выпуск read-only: "
          f"{manifest['read_only']}")
    print(f"Ограничений всего: {manifest['known_limitations_total']} · главных для "
          f"выпуска: {manifest['major_release_limitations_count']} · незакрытых пробелов "
          f"управления: {len(manifest['unresolved_governance_gaps'])}")
    print(f"Манифест → {final / 'director_os_v1_release_manifest.json'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
