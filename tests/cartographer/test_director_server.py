"""Тесты минимальной раздачи закрытого кокпита (v1.1).

Предмет проверки — четыре обещания, данных ARB:
  1. наружу сокет не слушает никогда;
  2. раздаётся ТОЛЬКО разрешённый список, и обход пути невозможен по построению;
  3. приватный ответ несёт объявленные заголовки, и они не «почти те»;
  4. подмена версии атомарна: полусобранного комплекта браузер получить не может.

Каждый отказ проверяется вживую — поднятым сервером на свободном порту, а не чтением кода.
Порт измеряется у той же двери, которой потом отвечает проверяемый код: «кажется, свободен»
основанием не является.
"""
import http.client
import json
import socket
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cartographer import director_server as srv  # noqa: E402


def free_port():
    """Свободный порт, ИЗМЕРЕННЫЙ у того же семейства сокетов, что и сервер."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def make_bundle(root, *, name='bundle-1', digest='aaaabbbbccccddddeeeeffff',
                page='<!doctype html><title>x</title>'):
    d = Path(root) / name
    d.mkdir(parents=True)
    (d / 'index.html').write_text(page, encoding='utf-8')
    (d / 'manifest.webmanifest').write_text('{"name":"Director OS"}', encoding='utf-8')
    (d / 'icon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>',
                                encoding='utf-8')
    (Path(root) / 'current.json').write_text(
        json.dumps({'directory': name, 'semantic_digest': digest,
                    'built_at': '2026-09-20T00:00:00+00:00'}), encoding='utf-8')
    return d


class LiveServer:
    """Поднятый сервер на измеренном порту. Закрывается всегда."""

    def __init__(self, root):
        self.port = free_port()
        self.httpd, self.serving = srv.serve(root, self.port, serve_forever=False)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def request(self, path, method='GET', timeout=6):
        """Запрос к СВОЕЙ петле через http.client.

        Сторож офлайна в `tests/conftest.py` подменяет именно `urllib.request.urlopen`,
        и делает это против ЖИВОЙ сети. Разговор с собственным сокетом на 127.0.0.1
        живой сетью не является, поэтому обходить сторожа не приходится — он просто
        про другое. `http.client` выбран ещё и потому, что не «помогает» с путями:
        строка адреса уходит на сервер дословно, а именно её отказы мы и проверяем.
        """
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        try:
            conn.putrequest(method, path, skip_host=False, skip_accept_encoding=True)
            conn.endheaders()
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            conn.close()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TheSocketNeverFacesTheNetwork(unittest.TestCase):

    def test_binding_outside_loopback_is_refused(self):
        """Умолчание stdlib слушает ВСЕ интерфейсы; 30.08 на этом раздался репозиторий."""
        for host in ('0.0.0.0', '', '192.168.1.10', '::'):
            with self.assertRaises(srv.BundleError) as caught:
                srv.serve('/tmp', free_port(), host=host, serve_forever=False)
            self.assertIn('наружу', str(caught.exception))

    def test_the_default_host_is_loopback(self):
        self.assertEqual(srv.LOOPBACK, '127.0.0.1')

    def test_a_live_server_listens_on_loopback_only(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp)
            s = LiveServer(tmp)
            try:
                host, _port = s.httpd.server_address[:2]
                self.assertEqual(host, '127.0.0.1')
            finally:
                s.close()


class OnlyTheAllowlistIsReachable(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = make_bundle(self.tmp.name)
        # Файлы, которые лежат РЯДОМ и не должны быть достижимы ни под каким адресом.
        (self.dir / 'director_web_projection.json').write_text('{"секрет":"данные"}')
        (self.dir / 'freshness_state.json').write_text('{}')
        (self.dir / '_headers').write_text('/*\n  X: y\n')
        (Path(self.tmp.name) / 'evidence.json').write_text('{"владелец":"данные"}')
        self.s = LiveServer(self.tmp.name)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def test_every_allowed_address_is_served(self):
        for path in sorted(srv.ROUTES):
            status, headers, body = self.s.request(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(body, path)
            self.assertEqual(headers['Content-Type'], srv.ROUTES[path][1], path)

    def test_the_raw_projection_cannot_be_requested(self):
        """Опубликованная проекция была бы выгрузкой владельческих данных одним GET."""
        for name in srv.FORBIDDEN_NAMES:
            status, _h, body = self.s.request(f'/{name}')
            self.assertEqual(status, 404, name)
            self.assertNotIn('секрет', body.decode('utf-8', 'replace'))

    def test_path_traversal_of_every_shape_is_refused(self):
        """Трансляции пути нет вовсе — поэтому обходить нечего. Проверяем вживую."""
        for path in ('/../current.json', '/..%2fcurrent.json', '/%2e%2e/current.json',
                     '/%2e%2e%2fcurrent.json', '/./../evidence.json',
                     '/subdir/../index.html', '//etc/passwd', '/etc/passwd',
                     '/index.html%00.json', '/index.html/../current.json'):
            status, _h, _b = self.s.request(path)
            self.assertEqual(status, 404, path)

    def test_the_bundle_directory_itself_is_not_a_prefix(self):
        status, _h, _b = self.s.request(f'/{self.dir.name}/index.html')
        self.assertEqual(status, 404)

    def test_there_is_no_directory_listing(self):
        for path in ('/', '/index.html'):
            _s, headers, _b = self.s.request(path)
            self.assertNotIn('text/directory', headers.get('Content-Type', ''))
        status, _h, body = self.s.request('/evidence/')
        self.assertEqual(status, 404)
        self.assertNotIn('Directory listing', body.decode('utf-8', 'replace'))

    def test_the_pointer_file_is_not_reachable(self):
        self.assertEqual(self.s.request('/current.json')[0], 404)

    def test_an_absolute_local_path_is_not_reachable(self):
        self.assertEqual(self.s.request(f'/{self.dir}/index.html'.replace('//', '/'))[0],
                         404)


class OnlyGetAndHeadAreAccepted(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        make_bundle(self.tmp.name)
        self.s = LiveServer(self.tmp.name)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def test_get_and_head_work(self):
        self.assertEqual(self.s.request('/index.html', 'GET')[0], 200)
        status, headers, body = self.s.request('/index.html', 'HEAD')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'')            # тела у HEAD нет
        self.assertIn('Content-Length', headers)

    def test_every_mutating_method_is_405(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE'):
            status, headers, _b = self.s.request('/index.html', method)
            self.assertEqual(status, 405, method)
            self.assertEqual(headers.get('Allow'), 'GET, HEAD', method)

    def test_a_refused_method_still_carries_the_security_headers(self):
        """Отказ — тоже ответ: он не имеет права быть кешируемым или индексируемым."""
        _s, headers, _b = self.s.request('/index.html', 'POST')
        self.assertIn('no-store', headers['Cache-Control'])
        self.assertIn('noindex', headers['X-Robots-Tag'])

    def test_the_allowed_methods_constant_matches_the_behaviour(self):
        self.assertEqual(srv.ALLOWED_METHODS, ('GET', 'HEAD'))


class ThePrivateResponseCarriesItsHeaders(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        make_bundle(self.tmp.name)
        self.s = LiveServer(self.tmp.name)
        _s, self.headers, _b = self.s.request('/index.html')

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def test_cache_control_forbids_storing_the_response(self):
        value = self.headers['Cache-Control']
        for token in ('private', 'no-store', 'max-age=0', 'must-revalidate'):
            self.assertIn(token, value)

    def test_no_store_is_present_not_merely_no_cache(self):
        """`no-cache` разрешает ЗАПИСЬ в кеш с перепроверкой; `no-store` запрещает запись."""
        self.assertIn('no-store', self.headers['Cache-Control'])

    def test_robots_are_told_not_to_index_archive_or_snippet(self):
        for token in ('noindex', 'nofollow', 'noarchive', 'nosnippet'):
            self.assertIn(token, self.headers['X-Robots-Tag'])

    def test_the_csp_matches_the_real_shell_and_grants_nothing_broad(self):
        csp = self.headers['Content-Security-Policy']
        self.assertIn("default-src 'none'", csp)
        self.assertIn("connect-src 'none'", csp)      # сети у кокпита нет
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("form-action 'none'", csp)
        self.assertIn("worker-src 'none'", csp)       # service worker запрещён и политикой
        for broad in ('*', "'unsafe-eval'", 'https:', 'data: *'):
            self.assertNotIn(f'default-src {broad}', csp)

    def test_framing_is_denied(self):
        self.assertEqual(self.headers['X-Frame-Options'], 'DENY')

    def test_sniffing_and_referrers_are_closed(self):
        self.assertEqual(self.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(self.headers['Referrer-Policy'], 'no-referrer')

    def test_the_python_version_is_not_advertised(self):
        self.assertNotIn('Python', self.headers.get('Server', ''))

    def test_every_declared_header_actually_reaches_the_response(self):
        """Объявить заголовок и не доставить — та же незащищённость, только с запиской."""
        for name, value in srv.SECURITY_HEADERS:
            self.assertEqual(self.headers.get(name), value, name)


class TheVersionSwapIsAtomic(unittest.TestCase):

    def test_a_new_pointer_is_picked_up_whole(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp, name='b1', digest='1' * 24, page='<title>первый</title>')
            s = LiveServer(tmp)
            try:
                self.assertIn(b'\xd0\xbf\xd0\xb5\xd1\x80\xd0\xb2\xd1\x8b\xd0\xb9',
                              s.request('/index.html')[2])
                make_bundle(tmp, name='b2', digest='2' * 24, page='<title>второй</title>')
                body = s.request('/index.html')[2]
                self.assertIn('второй', body.decode())
            finally:
                s.close()

    def test_a_pointer_to_a_half_built_directory_keeps_the_old_copy(self):
        """Главная защита: неполный комплект НЕ подменяет исправный."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp, name='good', page='<title>исправный</title>')
            s = LiveServer(tmp)
            try:
                half = Path(tmp) / 'half'
                half.mkdir()
                (half / 'index.html').write_text('<title>полуфабрикат</title>')
                (Path(tmp) / 'current.json').write_text(
                    json.dumps({'directory': 'half', 'semantic_digest': 'x' * 24}))
                body = s.request('/index.html')[2].decode()
                self.assertIn('исправный', body)
                self.assertNotIn('полуфабрикат', body)
                self.assertGreaterEqual(s.serving.errors, 1)
            finally:
                s.close()

    def test_a_pointer_naming_a_path_instead_of_a_name_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ('../outside', '/etc', '.hidden', 'a/b'):
                (Path(tmp) / 'current.json').write_text(
                    json.dumps({'directory': bad, 'semantic_digest': 'z' * 24}))
                self.assertIsNone(srv.read_pointer(tmp), bad)

    def test_a_missing_pointer_is_a_distinct_state_not_a_crash(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(srv.read_pointer(tmp))
            with self.assertRaises(srv.BundleError):
                srv.load_bundle(tmp, None)

    def test_a_corrupt_pointer_reads_as_absent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'current.json').write_text('{сломано')
            self.assertIsNone(srv.read_pointer(tmp))

    def test_a_symlinked_file_leading_outside_the_bundle_is_refused(self):
        """Симлинк наружу — отказ, а не удобство: иначе каталог перестаёт быть границей."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            d = make_bundle(tmp, name='b')
            outside = Path(tmp) / 'outside.html'
            outside.write_text('<title>чужое</title>')
            (d / 'index.html').unlink()
            (d / 'index.html').symlink_to(outside)
            with self.assertRaises(srv.BundleError) as caught:
                srv.load_bundle(tmp, srv.read_pointer(tmp))
            self.assertIn('наружу', str(caught.exception))


class TheHealthEndpointCarriesNoOwnerData(unittest.TestCase):

    def test_health_answers_without_private_content(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            make_bundle(tmp, page='<title>КАПИТАЛ 101340.69</title>')
            s = LiveServer(tmp)
            try:
                status, headers, body = s.request(srv.HEALTH_PATH)
                self.assertEqual(status, 200)
                doc = json.loads(body)
                self.assertEqual(doc['status'], 'ok')
                self.assertTrue(doc['bundle_loaded'])
                self.assertNotIn('101340', body.decode())
                self.assertIn('no-store', headers['Cache-Control'])
            finally:
                s.close()


class NothingIsExecutedAndNothingLeaves(unittest.TestCase):

    def test_the_module_imports_no_subprocess_and_no_outbound_client(self):
        import ast
        tree = ast.parse((ROOT / 'scripts/cartographer/director_server.py').read_text())
        banned = {'subprocess', 'urllib', 'requests', 'asyncio', 'ftplib', 'smtplib'}
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append(node.module.split('.')[0])
        self.assertEqual(sorted(set(found) & banned), [])

    def test_no_call_can_execute_an_external_program(self):
        import ast
        tree = ast.parse((ROOT / 'scripts/cartographer/director_server.py').read_text())
        forbidden = {'run', 'Popen', 'system', 'execv', 'execvp', 'eval', 'exec',
                     'compile', '__import__'}
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.attr if isinstance(fn, ast.Attribute)
                        else fn.id if isinstance(fn, ast.Name) else None)
                if name in forbidden:
                    hits.append(name)
        self.assertEqual(hits, [])

    def test_the_route_table_is_the_only_source_of_filenames(self):
        """Ни одного имени файла вне таблицы: список — единственная дверь."""
        served = {name for name, _ctype in srv.ROUTES.values()}
        self.assertEqual(served, {'index.html', 'manifest.webmanifest', 'icon.svg'})
        self.assertEqual(served & set(srv.FORBIDDEN_NAMES), set())


if __name__ == '__main__':
    unittest.main()
