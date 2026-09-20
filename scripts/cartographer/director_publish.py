#!/usr/bin/env python3
"""Director Publish (v1.1 Epic 1) — детерминированная сборка приватного комплекта.

Что делает
==========
Один проход: принятые снимки → web-safe проекция → закрытая оболочка → комплект к выкладке.
Затем сравнивает ``semantic_digest`` проекции с тем, что уже опубликовано, и говорит одно из
трёх: ``PUBLISH`` (смысл изменился), ``SKIP`` (не изменился), ``NOT_MEASURED`` (сравнивать не
с чем). Третий исход — отдельный, а не «наверное, публиковать»: инвариант #17.

Чего НЕ делает, и это устроено структурно
=========================================
Пушер отсюда **не вызывается ни при каких флагах**. Ветки «запушить» в этом файле нет вовсе —
команда печатает готовую канонtical-строку и выходит. Так гарантия «выкладки не будет» держится
на отсутствии кода, а не на дисциплине вызывающего: флаг можно передать по ошибке, а
несуществующую ветку исполнить нельзя.

Почему такт решает ФАЙЛ, а не расписание
========================================
Та же идиома, что у витрины чисел сайта (``build_site_numbers.py --if-due``): команда
безопасна к частому зову и ничего не делает, пока смысл не изменился. Иначе «раз в час»
держалось бы на том, что никто не трогал расписание.

Политика свежести объявлена ЗДЕСЬ (``FRESHNESS``), а не в расписании: такт слоя не может быть
чаще, чем меняются его собственные источники. Публиковать капитал раз в пять минут, когда его
источники пишутся раз в сутки, — это выдуманная свежесть, а не свежесть.

LLM запрещён. Сети нет. Ничего не исполняется и никуда не отправляется.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.cartographer import diff as diff_mod  # noqa: E402
from scripts.cartographer import web_projection as projection_mod  # noqa: E402
from scripts.cartographer import web_shell as shell_mod  # noqa: E402

#: Объявленная политика свежести. Основание каждого такта — КЕМ и КАК ЧАСТО пишутся
#: источники слоя, а не пожелание «побыстрее».
FRESHNESS = {
    'CAPITAL': {
        'tact': 'DAILY_PLUS_ON_CHANGE',
        'basis': 'источники капитала пишет дневной цикл (08:00 local); чаще — выдуманная '
                 'свежесть',
        'sources_written_by': 'daily_cycle',
    },
    'STUDIO': {
        'tact': 'HOURLY_PLUS_ON_CHANGE',
        'basis': 'источники надёжности и работы пишутся мониторами с тактом 300–3600 с; '
                 'часовой такт кокпита их не опережает',
        'sources_written_by': 'watchdog · self_heal · cycle_health · agent_health · '
                              'uptime_monitor · orchestrator',
    },
    'BUILD': {
        'tact': 'ON_CHANGE',
        'basis': 'состояние Bridge и аудит действий меняются редко; измерено: дайджест '
                 'аудита не сдвинулся между пересборками',
        'sources_written_by': 'bridge · action audit',
    },
}

#: Что уходит на живой хост. Ровно три файла — и ни одного сырого набора данных.
#: Проекция рендерится В страницу, а не публикуется рядом с ней: опубликованный
#: `director_web_projection.json` был бы выгрузкой владельческих данных одним запросом,
#: тогда как та же правда, разложенная по экрану, требует и Access, и человека.
#: `_headers` входит в набор намеренно: без него политика кеша не доедет до ответа,
#: а «объявили, но не доставили» — это та же незащищённость, только с запиской.
PUBLISHED_FILES = (shell_mod.SHELL_FILE, shell_mod.MANIFEST_FILE, shell_mod.ICON_FILE,
                   '_headers')

#: Улики сборки: остаются НА МАШИНЕ и на хост не уезжают никогда.
LOCAL_ONLY_FILES = ('director_web_projection.json', 'freshness_state.json')

#: Каталоги внутри комплекта: что публикуется и что остаётся локально.
PUBLISH_DIR = 'publish'
EVIDENCE_DIR = 'evidence'

VERDICTS = ('PUBLISH', 'SKIP', 'NOT_MEASURED')

#: Ответ приватного кокпита не должен лежать в кеше браузера дольше сессии.
#: `no-store` запрещает запись вовсе; `private` запрещает кеш посредникам.
CACHE_HEADERS = """# Приватный кокпит владельца: ответ не кешируется ни браузером, ни посредником.
# Проверено на живом сайте: объявленный здесь Cache-Control доходит до ответа.
/*
  Cache-Control: private, no-store, max-age=0, must-revalidate
  X-Robots-Tag: noindex, nofollow, noarchive
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Cross-Origin-Opener-Policy: same-origin
  Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
"""

#: Четыре разных времени. Их нельзя сводить в одно: «HTML не перевыкладывали» и
#: «смысл устарел» — разные утверждения, и склеив их, кокпит выглядел бы протухшим
#: ровно тогда, когда он свежее всего (дайджест не изменился, значит менять нечего).
FRESHNESS_FIELDS = ('last_check', 'last_successful_build',
                    'last_semantic_change', 'last_successful_publish')


def read_freshness_state(path):
    """Прошлое состояние свежести, либо пустое. Отсутствие — не ошибка."""
    p = Path(path) if path else None
    if not p or not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {}


def next_freshness_state(previous, *, digest, now, published_digest=None):
    """Новое состояние. Каждое поле отвечает на СВОЙ вопрос.

    ``last_semantic_change`` двигается только при смене дайджеста — иначе он врал бы,
    что смысл меняется каждый прогон. ``last_successful_publish`` эта команда не
    выставляет: выкладку она не делает, и штамповать её было бы ложью. Он берётся из
    прошлого состояния либо из совпадения с уже опубликованным дайджестом.
    """
    prev_digest = (previous or {}).get('semantic_digest')
    state = {
        'semantic_digest': digest,
        'last_check': now,
        'last_successful_build': now,
        'last_semantic_change': (now if digest != prev_digest
                                 else (previous or {}).get('last_semantic_change')),
        'last_successful_publish': (previous or {}).get('last_successful_publish'),
    }
    if published_digest is not None and published_digest == digest:
        # Опубликованное совпало с собранным ⇒ выкладка этого смысла состоялась.
        state['last_successful_publish'] = (
            (previous or {}).get('last_successful_publish') or now)
    state['unchanged_is_not_stale'] = (
        'совпадение дайджеста означает, что менять нечего. Неизменившийся смысл НЕ '
        'является устаревшим: смотреть надо на «последнюю проверку», а не на дату HTML')
    return state


def activate(serve_root, publish_dir, *, digest, now=None):
    """Ставит собранный комплект в раздачу атомарно.

    Каталог с файлами копируется под НОВЫМ именем, и только потом указатель
    ``current.json`` переписывается одним ``os.replace``. Полусобранного комплекта
    браузер получить не может: до подмены указателя сервер о новом каталоге не знает,
    после — читает его целиком, прежде чем подменить свою копию в памяти.

    Симлинков здесь нет намеренно: сервер обязан отказывать файлу, ведущему наружу,
    и чинить это исключением ради удобства активации было бы снятием защиты.
    """
    root = refuse_inside_repository(serve_root, 'корень раздачи')
    src = Path(publish_dir)
    if not src.is_dir():
        raise PublishError(f'нечего ставить в раздачу: {src} не каталог')
    # Режим задаётся ЯВНО и проверяется у существующего каталога тоже: `mkdir` с
    # umask по умолчанию даёт 0755, и корень раздачи приватных данных оказался бы
    # читаемым любому пользователю машины. Найдено замером ARB 20.09 — прежний отчёт
    # называл 0600, но это были ФАЙЛЫ, а каталоги никто не мерил.
    _private_mkdir(root, parents=True)
    for d in [a for a in root.parents if _is_serve_parent(a)]:
        if (d.stat().st_mode & 0o777) != 0o700:
            os.chmod(d, 0o700)
    stamp = (now or _utcnow()).replace(':', '').replace('-', '')[:15]
    target = root / f'bundle-{stamp}-{digest[:12]}'
    if target.exists():
        raise PublishError(f'{target} уже существует; каждая активация — новый каталог')
    staging = root / (target.name + '.incomplete')
    if staging.exists():
        raise PublishError(f'{staging} остался от прерванной активации; отодвиньте его')
    _private_mkdir(staging)
    for name in PUBLISHED_FILES:
        f = src / name
        if not f.is_file():
            raise PublishError(f'в комплекте нет обязательного файла: {name}')
        (staging / name).write_bytes(f.read_bytes())
        os.chmod(staging / name, 0o600)
    os.rename(staging, target)

    pointer = root / 'current.json'
    tmp = root / 'current.json.tmp'
    tmp.write_text(json.dumps({'directory': target.name, 'semantic_digest': digest,
                               'built_at': now or _utcnow()},
                              ensure_ascii=False, indent=1), encoding='utf-8')
    os.chmod(tmp, 0o600)
    os.replace(tmp, pointer)      # ← одна операция: указатель либо старый, либо новый
    return target


#: Корень репозитория: `scripts/cartographer/x.py` → на три уровня вверх.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _private_mkdir(path, *, parents=False):
    """Каталог приватных данных с режимом 0700 — включая ПРОМЕЖУТОЧНЫЕ.

    `Path.mkdir(parents=True, mode=0o700)` применяет режим только к ПОСЛЕДНЕМУ каталогу;
    промежуточные создаются по умолчанию, то есть 0755. Замер 20.09: девять рабочих
    каталогов оказались читаемы любому пользователю машины, а внутри них лежит полная
    проекция владельца. Тот же класс, что и с корнем раздачи.
    """
    path = Path(path)
    if parents:
        chain = [a for a in reversed(path.parents) if not a.exists()]
        for parent in chain:
            parent.mkdir(mode=0o700)
            os.chmod(parent, 0o700)
    path.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _is_serve_parent(path):
    """Родитель корня раздачи, который мы вправе ужесточить.

    Ужимаем ТОЛЬКО собственный каталог раздачи, не поднимаясь до домашнего: менять
    права домашнего каталога владельца — не наше дело.
    """
    return path.name == 'studio-os-serve'


def refuse_inside_repository(path, what):
    """Отказ писать сгенерированные данные внутрь дерева кода.

    `diff.validate_output` защищает от попадания выхода внутрь НАБЛЮДАЕМЫХ наборов —
    это другой вопрос. Найдено сторожем доставки 20.09: каталог репозитория ни одним
    наблюдаемым набором не является, и команда согласилась бы записать туда комплект.
    Репозиторий ПУБЛИЧНЫЙ, поэтому такая запись — один `git add` от утечки навсегда.
    """
    target = Path(path).resolve()
    if target == REPO_ROOT or REPO_ROOT in target.parents:
        raise PublishError(
            f'{what} внутри дерева кода ({target}) — запрещено: репозиторий публичный, '
            'и сгенерированные владельческие данные в нём один `git add` от утечки')
    return target


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


class PublishError(Exception):
    pass


#: Порядок пересборки улик Cartographer и зависимости между ними.
#: Каждый шаг — УЖЕ существующий сборщик со своим контрактом; здесь только проводка.
#: Список объявлен данными, а не последовательностью вызовов: пропущенный шаг тогда
#: виден глазами, а не прячется в середине функции.
REBUILD_STEPS = (
    ('snapshot',      ('--production', '{prod}', '--output', '{snap}')),
    ('authority_map', ('--production', '{prod}', '--cartographer', '{snap}',
                       '--output', '{auth}')),
    ('reliability',   ('--production', '{prod}', '--cartographer', '{snap}',
                       '--authority', '{auth}', '--output', '{rel}')),
    ('work',          ('--production', '{prod}', '--cartographer', '{snap}',
                       '--reliability', '{rel}', '--output', '{work}')),
    ('investments',   ('--production', '{prod}', '--output', '{inv}')),
    ('governance',    ('--production', '{prod}', '--output', '{gov}')),
    ('actions',       ('--production', '{prod}', '--governance', '{gov}',
                       '--output', '{act}')),
    ('director',      ('--work', '{work}', '--reliability', '{rel}',
                       '--authority', '{auth}', '--output', '{dir}')),
)

#: Что каждый шаг кладёт и под каким именем это ждёт сборка комплекта.
REBUILD_ARTIFACTS = {
    'rel': 'reliability_snapshot.json',
    'work': 'work_snapshot.json',
    'inv': 'investment_snapshot.json',
    'gov': 'governance_snapshot.json',
    'act': 'action_authority_audit.json',
    'dir': 'director_center.json',
}


class RebuildError(PublishError):
    pass


def rebuild_evidence(production, work_root, *, now=None):
    """Пересобирает улики Cartographer из канонических источников.

    Сборщики зовутся ВНУТРИ процесса (`main(argv)`), а не через оболочку: модуль обязан
    оставаться офлайн по построению, а `subprocess` — это дверь наружу, которую тесты
    запрещают. Каждый сборщик несёт свой контракт и отказывает сам; здесь только проводка
    и сбор результатов в один каталог.

    Отказ любого шага — отказ всего цикла с НАЗВАННЫМ шагом. Частично собранный комплект
    не собирается: половина улик выглядела бы как целая.
    """
    import importlib

    stamp = (now or _utcnow()).replace(':', '').replace('-', '')[:15]
    root = refuse_inside_repository(Path(work_root) / f'evidence-{stamp}', 'улики')
    _private_mkdir(root, parents=True)
    slots = {'prod': str(production)}
    for key in ('snap', 'auth', 'rel', 'work', 'inv', 'gov', 'act', 'dir'):
        slots[key] = str(root / key)

    done = []
    for name, template in REBUILD_STEPS:
        module = importlib.import_module(f'scripts.cartographer.{name}')
        argv = [part.format(**slots) for part in template]
        try:
            code = module.main(argv)
        except SystemExit as exc:          # сборщики отказывают через SystemExit
            code = exc.code if isinstance(exc.code, int) else 1
        except Exception as exc:           # noqa: BLE001 — шаг обязан быть НАЗВАН
            raise RebuildError(f'шаг «{name}» упал: {exc!r}') from exc
        if code not in (0, None):
            raise RebuildError(f'шаг «{name}» отказал с кодом {code}')
        done.append(name)

    # Сборка комплекта ждёт все улики в ОДНОМ каталоге под каноническими именами.
    bundle = _private_mkdir(root / 'bundle')
    missing = []
    for key, filename in REBUILD_ARTIFACTS.items():
        src = Path(slots[key]) / filename
        if not src.is_file():
            missing.append(f'{key}:{filename}')
            continue
        (bundle / filename).write_bytes(src.read_bytes())
        os.chmod(bundle / filename, 0o600)
    if missing:
        raise RebuildError('шаги отработали, но улик нет: ' + ', '.join(missing))
    return bundle, done


def publish_verdict(new_digest, published_digest):
    """Три исхода, и они различимы.

    ``NOT_MEASURED`` — не «на всякий случай публикуем»: неизвестность обязана быть
    отдельным значением, иначе первый же пустой файл превратится в «изменилось».
    """
    if not new_digest:
        return 'NOT_MEASURED', 'дайджест новой проекции не вычислен'
    if published_digest is None:
        return 'NOT_MEASURED', ('опубликованного дайджеста нет — сравнивать не с чем; '
                                'это НЕ значит «изменилось»')
    if new_digest == published_digest:
        return 'SKIP', 'смысл не изменился: дайджест совпал'
    return 'PUBLISH', f'смысл изменился: {published_digest[:12]} → {new_digest[:12]}'


def read_published_digest(path):
    """Дайджест уже опубликованной проекции, либо ``None``, если её нет."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding='utf-8')).get('semantic_digest')
    except (ValueError, OSError):
        return None


def read_serving_digest(serve_root):
    """Что РАЗДАЁТСЯ прямо сейчас — по указателю корня раздачи.

    При туннельной архитектуре «опубликовано» означает «лежит в активном каталоге», а
    не «записано в отдельный файл». Без этого вердикт сравнивал бы не с тем, и задание
    переподставляло бы комплект каждый час даже когда менять нечего: `SKIP` не
    наступал бы никогда, а «ничего не делать при неизменном смысле» осталось бы словами.
    """
    if not serve_root:
        return None
    pointer = Path(serve_root) / 'current.json'
    if not pointer.exists():
        return None
    try:
        return json.loads(pointer.read_text(encoding='utf-8')).get('semantic_digest')
    except (ValueError, OSError):
        return None


def build_bundle(*, bundle, output, bridge=None, intake=None, architect=None, cio=None,
                 state_path=None, published=None, now=None,
                 published_digest_override=None):
    """Собирает комплект в ``output``: ``publish/`` (уезжает) и ``evidence/`` (остаётся).

    Разделение каталогом, а не дисциплиной: выложить лишнее можно только указав другой
    каталог вручную, а не забыв исключить файл.
    """
    out = refuse_inside_repository(output, 'комплект')
    if out.exists():
        raise PublishError(f'{out} уже существует; каждый прогон пишет новый каталог')
    stamp = now or _utcnow()

    def read(name):
        doc, _ = projection_mod.reliability_mod._read_json(Path(bundle) / name)
        return doc

    projection = projection_mod.build_projection(
        investments=read('investment_snapshot.json'),
        reliability=read('reliability_snapshot.json'),
        work=read('work_snapshot.json'),
        governance=read('governance_snapshot.json'),
        director=read('director_center.json'),
        actions=read('action_authority_audit.json'),
        bridge=bridge, intake=intake)
    projection_mod.validate_projection(projection, 'director_publish')

    digest = projection['semantic_digest']
    published_digest = (published_digest_override if published_digest_override is not None
                        else (read_published_digest(published) if published else None))
    state = next_freshness_state(read_freshness_state(state_path), digest=digest,
                                 now=stamp, published_digest=published_digest)

    page = shell_mod.shell_html(projection, architect=architect, cio=cio, bridge=bridge,
                                freshness=state)
    shell_mod.validate_shell(page, 'director_publish')

    diff_mod.validate_output(out, [Path(bundle)])
    staging = out.with_name(out.name + '.incomplete')
    if staging.exists():
        raise PublishError(f'{staging} остался от прерванного прогона; отодвиньте его')
    # staging создаётся ЯВНО: как родитель он получил бы режим по умолчанию.
    _private_mkdir(staging, parents=True)
    pub = _private_mkdir(staging / PUBLISH_DIR)
    ev = _private_mkdir(staging / EVIDENCE_DIR)

    (pub / shell_mod.SHELL_FILE).write_text(page, encoding='utf-8')
    (pub / shell_mod.MANIFEST_FILE).write_text(
        json.dumps(shell_mod.manifest(), ensure_ascii=False, indent=1), encoding='utf-8')
    (pub / shell_mod.ICON_FILE).write_text(shell_mod.ICON_SVG, encoding='utf-8')
    # Заголовки кеша объявляются рядом с файлами: приватный ответ не должен переживать
    # выход из системы. Механизм проверен на живом сайте — `_headers` доходит до ответа.
    (pub / '_headers').write_text(CACHE_HEADERS, encoding='utf-8')

    (ev / 'director_web_projection.json').write_text(
        json.dumps(projection, ensure_ascii=False, indent=1, allow_nan=False),
        encoding='utf-8')
    (ev / 'freshness_state.json').write_text(
        json.dumps({**state, 'policy': FRESHNESS}, ensure_ascii=False, indent=1),
        encoding='utf-8')

    for d, names in ((pub, PUBLISHED_FILES), (ev, LOCAL_ONLY_FILES)):
        for name in names:
            os.chmod(d / name, 0o600)
    os.rename(staging, out)

    # Состояние свежести обязано лечь ТУДА, ОТКУДА его прочтёт следующий прогон.
    # Первая редакция писала его только в evidence/ каждого комплекта, а читала по
    # --state — файла там не было никогда, поэтому каждый прогон считал дайджест новым
    # и «последнее изменение смысла» двигалось бы ежечасно. Ровно тот ложный сдвиг,
    # против которого поле и существует.
    if state_path:
        target = refuse_inside_repository(state_path, 'состояние свежести')
        _private_mkdir(target.parent, parents=True)
        tmp = target.with_name(target.name + '.tmp')
        tmp.write_text(json.dumps({**state, 'policy': FRESHNESS},
                                  ensure_ascii=False, indent=1), encoding='utf-8')
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)      # одна операция: состояние либо старое, либо новое
    return projection, page, state


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--bundle', help='каталог уже принятых снимков Director OS')
    ap.add_argument('--rebuild-from', help='корень прод-дерева: пересобрать улики '
                                           'Cartographer из канонических источников')
    ap.add_argument('--work-root', help='куда класть пересобранные улики (вне репозитория)')
    ap.add_argument('--output', required=True, help='новый каталог комплекта')
    ap.add_argument('--published', help='уже опубликованный director_web_projection.json '
                                        '— для сравнения дайджестов')
    ap.add_argument('--bridge', help='JSON: наблюдённое состояние Bridge')
    ap.add_argument('--intake', help='JSON: каналы приёма владельца')
    ap.add_argument('--architect', help='JSON: состояние Архитектора')
    ap.add_argument('--cio', help='JSON: состояние CIO')
    ap.add_argument('--state', help='freshness_state.json прошлого прогона')
    ap.add_argument('--verdict-exit-code', action='store_true',
                    help='вернуть вердикт кодом возврата (0/3/2). НЕ для launchd: там '
                         'любой ненулевой код читается как поломка агента')
    ap.add_argument('--activate-root', help='корень раздачи: поставить комплект в работу '
                                            'атомарно (локально, наружу ничего не идёт)')
    args = ap.parse_args(argv)

    load = lambda raw: (json.loads(raw) if raw else None)  # noqa: E731
    bundle = args.bundle
    rebuilt = []
    if args.rebuild_from:
        if not args.work_root:
            raise SystemExit('--rebuild-from требует --work-root: улики кладутся ВНЕ '
                             'репозитория, и каталог обязан быть назван явно')
        try:
            path, rebuilt = rebuild_evidence(args.rebuild_from, args.work_root)
            bundle = str(path)
        except (RebuildError, PublishError) as exc:
            raise SystemExit(f'ПЕРЕСБОРКА НЕ ВЫПОЛНЕНА: {exc}\nКомплект не собран.')
    if not bundle:
        raise SystemExit('нужен либо --bundle, либо --rebuild-from')
    try:
        projection, page, state = build_bundle(
            published_digest_override=(read_published_digest(args.published)
                                       if args.published
                                       else read_serving_digest(args.activate_root)),
            bundle=bundle, output=args.output, bridge=load(args.bridge),
            intake=load(args.intake), architect=load(args.architect), cio=load(args.cio),
            state_path=args.state, published=args.published)
    except (PublishError, projection_mod.WebProjectionError,
            shell_mod.ShellError, ValueError) as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nКомплект не собран.')

    digest = projection['semantic_digest']
    # Что считать «опубликованным»: явный файл, если назван, иначе — то, что РАЗДАЁТСЯ.
    published_digest = (read_published_digest(args.published) if args.published
                        else read_serving_digest(args.activate_root))
    verdict, reason = publish_verdict(digest, published_digest)
    out = Path(args.output)
    stats = projection['redaction_stats']
    activated = None
    if args.activate_root and verdict != 'SKIP':
        try:
            activated = activate(args.activate_root, out / PUBLISH_DIR, digest=digest)
        except PublishError as exc:
            raise SystemExit(f'АКТИВАЦИЯ НЕ ВЫПОЛНЕНА: {exc}\nКомплект собран, '
                             'но в раздачу не поставлен — указатель не тронут.')

    if rebuilt:
        print(f'  улики пересобраны: {len(rebuilt)} шагов — ' + ' · '.join(rebuilt))
    print(f'Комплект → {out}')
    print(f'  {PUBLISH_DIR}/ (уезжает): ' + ' · '.join(PUBLISHED_FILES))
    print(f'  {EVIDENCE_DIR}/ (остаётся): ' + ' · '.join(LOCAL_ONLY_FILES))
    print(f'  страница {len(page.encode("utf-8"))} байт')
    print('  свежесть: ' + ' · '.join(
        f'{k}={str(state.get(k) or "не измерено")[:19]}' for k in FRESHNESS_FIELDS))
    print(f'  как есть {stats["SAFE_FOR_PRIVATE_WEB"]} · отредактировано {stats["REDACTED"]} '
          f'· только локально {stats["LOCAL_ONLY"]} · UNKNOWN заблокировано '
          f'{stats["UNKNOWN_BLOCKED"]}')
    print(f'  REAL CAPITAL PROVEN: '
          f'{projection["layers"]["CAPITAL"].get("real_capital_proven")} · '
          f'действия: {projection["layers"]["BUILD"]["actions_enabled"]}')
    print(f'  дайджест: {digest}')
    print(f'  ВЕРДИКТ ВЫКЛАДКИ: {verdict} — {reason}')
    if activated:
        print(f'  поставлено в раздачу атомарно: {activated.name}')
    elif args.activate_root:
        print('  в раздачу не ставил: смысл не изменился (SKIP)')
    print()
    print('  Выкладки в смысле Pages здесь НЕТ: туннель раздаёт ТОТ каталог, который')
    print('  активирован выше. Сгенерированные владельческие данные в git не уходят —')
    print('  репозиторий публичный, и команда пуша для них не печатается намеренно.')
    if not args.activate_root:
        print('  каталог раздачи не указан (--activate-root) — комплект собран и лежит '
              'локально')

    # Код возврата по умолчанию — 0 при УСПЕХЕ, независимо от вердикта.
    #
    # Первая редакция несла вердикт кодом (0/3/2), и канонический гейт отказал: он ждёт
    # 0, а первый прогон честно отвечает 2 («сравнивать не с чем»). Дефект глубже гейта:
    # для launchd и сторожей здоровья ЛЮБОЙ ненулевой код означает поломку, поэтому шаг,
    # выходящий 3 каждый час при «менять нечего», выглядел бы вечно сломанным — и
    # настоящая поломка утонула бы в этом шуме.
    #
    # Вердикт живёт там, где его можно прочитать: в напечатанной строке и в
    # freshness_state.json. Код возврата принадлежит менеджеру процессов, а не нам.
    # Флаг ниже оставлен для человека и скриптов, которым вердикт нужен кодом.
    if args.verdict_exit_code:
        return {'PUBLISH': 0, 'SKIP': 3, 'NOT_MEASURED': 2}[verdict]
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
