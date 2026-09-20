#!/usr/bin/env python3
"""Director Server (v1.1) — минимальная раздача закрытого кокпита. НЕ бэкенд приложения.

Почему он новый, а не переиспользованный
========================================
Замер 20.09 по репозиторию: подходящего компонента нет.
* ``com.spa.dashboard`` раздаёт **корень репозитория** (``http.server --directory <repo>``) —
  переиспользовать запрещено прямым условием ARB, и это тот самый компонент, который 30.08
  раздавал `.git` всей локальной сети;
* ``family_fund/http_server.py`` и ``api/whitelabel_api.py`` — JSON-API: принимают POST,
  ставят ``Access-Control-Allow-Origin: *``, статических файлов не раздают вовсе.

Как устроена защита от обхода пути
==================================
Трансляции пути НЕТ ВООБЩЕ. Запрошенная строка сверяется со словарём разрешённых адресов и
либо совпадает дословно, либо получает 404. Ни ``..``, ни ``%2e%2e``, ни симлинк, ни абсолютный
путь не могут вывести за каталог, потому что путь из запроса **никогда не превращается в путь
на диске**. Это сильнее любой проверки-нормализации: нормализацию можно обойти, отсутствующий
код — нельзя.

Содержимое держится В ПАМЯТИ, и подмена версии атомарна
=======================================================
Сервер читает комплект целиком и хранит его в памяти. Сборка пишет НОВЫЙ каталог и обновляет
указатель ``current.json``; сервер замечает смену указателя, читает новый комплект ЦЕЛИКОМ и
только потом подменяет свою копию одной операцией. Поэтому браузер не может получить
полусобранный комплект — не по расторопности, а по построению. Симлинки при этом не нужны.

Чего он не делает
=================
Ни POST, ни PUT, ни PATCH, ни DELETE, ни загрузок, ни проксирования, ни исполнения кода, ни
списков каталога. Снимки Cartographer, ``director_web_projection.json`` и
``freshness_state.json`` в словаре разрешённых адресов отсутствуют — их нельзя запросить.

LLM запрещён. Наружу сервер не слушает: только 127.0.0.1.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOOPBACK = '127.0.0.1'
DEFAULT_PORT = 8788
POINTER_FILE = 'current.json'

#: Единственная карта «адрес → файл». Чего здесь нет, того не существует для сервера.
ROUTES = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/manifest.webmanifest': ('manifest.webmanifest', 'application/manifest+json'),
    '/icon.svg': ('icon.svg', 'image/svg+xml'),
}

#: Файлы, которые сервер обязан НЕ знать. Список существует ради теста: он превращает
#: «мы вроде не раздаём» в проверяемое утверждение.
FORBIDDEN_NAMES = (
    'director_web_projection.json', 'freshness_state.json', 'portal_snapshot.json',
    'authority_map.json', 'reliability_snapshot.json', 'work_snapshot.json',
    'investment_snapshot.json', 'governance_snapshot.json', 'director_center.json',
    'action_authority_audit.json', '_headers',
)

ALLOWED_METHODS = ('GET', 'HEAD')

#: Заголовки приватного ответа. CSP соответствует РЕАЛЬНОЙ оболочке: она инлайнит стиль и
#: один скрипт, грузит одну иконку и манифест — и ничего больше. Широких исключений нет.
SECURITY_HEADERS = (
    ('Cache-Control', 'private, no-store, max-age=0, must-revalidate'),
    ('Pragma', 'no-cache'),
    ('X-Robots-Tag', 'noindex, nofollow, noarchive, nosnippet'),
    ('X-Content-Type-Options', 'nosniff'),
    ('Referrer-Policy', 'no-referrer'),
    ('X-Frame-Options', 'DENY'),
    ('Cross-Origin-Opener-Policy', 'same-origin'),
    ('Cross-Origin-Resource-Policy', 'same-origin'),
    ('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), usb=()'),
    ('Content-Security-Policy',
     "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
     "img-src 'self' data:; manifest-src 'self'; connect-src 'none'; "
     "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
     "object-src 'none'; worker-src 'none'"),
)

#: /health отвечает БЕЗ приватных данных: он нужен туннелю и сторожам, а не владельцу.
HEALTH_PATH = '/health'


class BundleError(Exception):
    pass


def read_pointer(root):
    """Какой каталог сейчас актуален. Отсутствие указателя — отдельный, честный исход."""
    p = Path(root) / POINTER_FILE
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return None
    name = doc.get('directory')
    if not name or '/' in str(name) or str(name).startswith('.'):
        return None  # указатель обязан называть ИМЯ каталога, а не путь
    return {'directory': str(name), 'semantic_digest': doc.get('semantic_digest'),
            'built_at': doc.get('built_at')}


def load_bundle(root, pointer):
    """Комплект целиком в память. Либо весь, либо ничего: половины комплекта не бывает."""
    if pointer is None:
        raise BundleError('указателя current.json нет — раздавать нечего')
    base = (Path(root) / pointer['directory']).resolve()
    root_resolved = Path(root).resolve()
    if root_resolved not in base.parents and base != root_resolved:
        raise BundleError('каталог комплекта вне корня раздачи')
    bundle = {}
    for path, (name, ctype) in ROUTES.items():
        f = base / name
        # Симлинк за пределы каталога комплекта не принимается: сверяем РАЗРЕШЁННЫЙ путь.
        if not f.exists() or f.resolve().parent != base:
            raise BundleError(f'файл комплекта отсутствует или ведёт наружу: {name}')
        bundle[path] = (f.read_bytes(), ctype)
    return {'files': bundle, 'digest': pointer.get('semantic_digest'),
            'directory': pointer['directory'], 'built_at': pointer.get('built_at')}


class Serving:
    """Текущая копия в памяти. Подмена — одна операция присваивания."""

    def __init__(self, root):
        self.root = Path(root)
        self.state = None
        self.pointer = None
        self.reloads = 0
        self.errors = 0

    def refresh(self):
        pointer = read_pointer(self.root)
        if pointer is None:
            return False
        if self.pointer and pointer == self.pointer and self.state is not None:
            return False
        try:
            new_state = load_bundle(self.root, pointer)
        except BundleError:
            self.errors += 1
            return False          # старая копия продолжает раздаваться: fail-SAFE
        self.state, self.pointer = new_state, pointer   # ← атомарная подмена
        self.reloads += 1
        return True

    def get(self, path):
        if self.state is None:
            return None
        return self.state['files'].get(path)


def make_handler(serving):
    class DirectorHandler(BaseHTTPRequestHandler):
        server_version = 'director/1'
        sys_version = ''                     # версию Python наружу не сообщаем
        protocol_version = 'HTTP/1.1'

        def _headers(self, status, ctype, length):
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(length))
            for name, value in SECURITY_HEADERS:
                self.send_header(name, value)
            self.end_headers()

        def _refuse(self, status, message):
            body = json.dumps({'error': message}, ensure_ascii=False).encode()
            self._headers(status, 'application/json; charset=utf-8', len(body))
            if self.command != 'HEAD':
                self.wfile.write(body)

        def _serve(self, head_only=False):
            # Запрос отрезается от строки запроса и фрагмента, но в путь на диске
            # НЕ превращается: дальше только сверка со словарём.
            path = self.path.split('?', 1)[0].split('#', 1)[0]
            if path == HEALTH_PATH:
                serving.refresh()
                body = json.dumps({
                    'status': 'ok',
                    'bundle_loaded': serving.state is not None,
                    'semantic_digest': (serving.state or {}).get('digest'),
                    'reloads': serving.reloads, 'load_errors': serving.errors,
                    'checked_at': datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False).encode()
                self._headers(HTTPStatus.OK, 'application/json; charset=utf-8', len(body))
                if not head_only:
                    self.wfile.write(body)
                return
            serving.refresh()
            found = serving.get(path)
            if found is None:
                self._refuse(HTTPStatus.NOT_FOUND, 'не найдено')
                return
            body, ctype = found
            self._headers(HTTPStatus.OK, ctype, len(body))
            if not head_only:
                self.wfile.write(body)

        def do_GET(self):
            self._serve()

        def do_HEAD(self):
            self._serve(head_only=True)

        # Всё остальное отвергается ОДНОЙ веткой: ветки «исполнить» здесь нет.
        def _method_not_allowed(self):
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header('Allow', ', '.join(ALLOWED_METHODS))
            self.send_header('Content-Length', '0')
            for name, value in SECURITY_HEADERS:
                self.send_header(name, value)
            self.end_headers()

        do_POST = do_PUT = do_PATCH = do_DELETE = _method_not_allowed
        do_OPTIONS = do_TRACE = do_CONNECT = _method_not_allowed

        def log_message(self, format, *args):  # noqa: A002 — подпись базового класса
            # В журнал не попадает ни строка запроса целиком, ни заголовки: приватный
            # кокпит не должен оставлять следов содержимого в /tmp.
            sys.stderr.write(f'director/1 {self.command} {self.address_string()} '
                             f'{args[1] if len(args) > 1 else ""}\n')

    return DirectorHandler


def serve(root, port=DEFAULT_PORT, host=LOOPBACK, serve_forever=True):
    """Поднимает раздачу. ``host`` по умолчанию и по смыслу — только петля."""
    if host not in ('127.0.0.1', '::1', 'localhost'):
        raise BundleError(f'раздача наружу запрещена: host={host!r}. Только петля; '
                          'наружу ведёт туннель, а не сокет')
    serving = Serving(root)
    serving.refresh()
    httpd = ThreadingHTTPServer((host, int(port)), make_handler(serving))
    httpd.daemon_threads = True
    if serve_forever:
        print(f'director/1 слушает http://{host}:{port}/ · комплект '
              f'{(serving.state or {}).get("directory") or "НЕ ЗАГРУЖЕН"}', flush=True)
        try:
            httpd.serve_forever()
        finally:
            httpd.server_close()
    return httpd, serving


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', required=True,
                    help='корень раздачи: там лежит current.json и каталоги комплектов')
    ap.add_argument('--port', type=int, default=DEFAULT_PORT)
    args = ap.parse_args(argv)
    if not Path(args.root).is_dir():
        raise SystemExit(f'корень раздачи не найден: {args.root}')
    try:
        serve(args.root, args.port)
    except BundleError as exc:
        raise SystemExit(f'ОТКАЗ: {exc}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
