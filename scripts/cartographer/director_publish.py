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
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for d in (root, *[a for a in root.parents if _is_serve_parent(a)]):
        if (d.stat().st_mode & 0o777) != 0o700:
            os.chmod(d, 0o700)
    stamp = (now or _utcnow()).replace(':', '').replace('-', '')[:15]
    target = root / f'bundle-{stamp}-{digest[:12]}'
    if target.exists():
        raise PublishError(f'{target} уже существует; каждая активация — новый каталог')
    staging = root / (target.name + '.incomplete')
    if staging.exists():
        raise PublishError(f'{staging} остался от прерванной активации; отодвиньте его')
    staging.mkdir(mode=0o700)
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


def build_bundle(*, bundle, output, bridge=None, intake=None, architect=None, cio=None,
                 state_path=None, published=None, now=None):
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
    published_digest = read_published_digest(published) if published else None
    state = next_freshness_state(read_freshness_state(state_path), digest=digest,
                                 now=stamp, published_digest=published_digest)

    page = shell_mod.shell_html(projection, architect=architect, cio=cio, bridge=bridge,
                                freshness=state)
    shell_mod.validate_shell(page, 'director_publish')

    diff_mod.validate_output(out, [Path(bundle)])
    staging = out.with_name(out.name + '.incomplete')
    if staging.exists():
        raise PublishError(f'{staging} остался от прерванного прогона; отодвиньте его')
    pub = staging / PUBLISH_DIR
    ev = staging / EVIDENCE_DIR
    pub.mkdir(parents=True, mode=0o700)
    ev.mkdir(parents=True, mode=0o700)

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
    return projection, page, state


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--bundle', required=True, help='каталог принятых снимков Director OS')
    ap.add_argument('--output', required=True, help='новый каталог комплекта')
    ap.add_argument('--published', help='уже опубликованный director_web_projection.json '
                                        '— для сравнения дайджестов')
    ap.add_argument('--bridge', help='JSON: наблюдённое состояние Bridge')
    ap.add_argument('--intake', help='JSON: каналы приёма владельца')
    ap.add_argument('--architect', help='JSON: состояние Архитектора')
    ap.add_argument('--cio', help='JSON: состояние CIO')
    ap.add_argument('--state', help='freshness_state.json прошлого прогона')
    ap.add_argument('--activate-root', help='корень раздачи: поставить комплект в работу '
                                            'атомарно (локально, наружу ничего не идёт)')
    args = ap.parse_args(argv)

    load = lambda raw: (json.loads(raw) if raw else None)  # noqa: E731
    try:
        projection, page, state = build_bundle(
            bundle=args.bundle, output=args.output, bridge=load(args.bridge),
            intake=load(args.intake), architect=load(args.architect), cio=load(args.cio),
            state_path=args.state, published=args.published)
    except (PublishError, projection_mod.WebProjectionError,
            shell_mod.ShellError, ValueError) as exc:
        raise SystemExit(f'INCOMPATIBLE INPUT: {exc}\nКомплект не собран.')

    digest = projection['semantic_digest']
    verdict, reason = publish_verdict(digest, read_published_digest(args.published)
                                      if args.published else None)
    out = Path(args.output)
    stats = projection['redaction_stats']
    activated = None
    if args.activate_root and verdict != 'SKIP':
        try:
            activated = activate(args.activate_root, out / PUBLISH_DIR, digest=digest)
        except PublishError as exc:
            raise SystemExit(f'АКТИВАЦИЯ НЕ ВЫПОЛНЕНА: {exc}\nКомплект собран, '
                             'но в раздачу не поставлен — указатель не тронут.')

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

    # Код возврата несёт вердикт: 0 — публиковать, 3 — нечего, 2 — не измерено.
    # Единица под вердикт НЕ занята намеренно: ею отвечает сам python на исключение,
    # и смешивать «сломалось» с «не изменилось» значит потерять оба ответа.
    return {'PUBLISH': 0, 'SKIP': 3, 'NOT_MEASURED': 2}[verdict]


if __name__ == '__main__':
    raise SystemExit(main())
