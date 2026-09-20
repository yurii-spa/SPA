"""Сторож доставки: сгенерированные владельческие данные НЕ попадают в репозиторий.

Зачем именно сторож, а не дисциплина. Репозиторий `yurii-spa/SPA` — ПУБЛИЧНЫЙ (замер
20.09: `api.github.com/repos/yurii-spa/SPA` → `visibility=public`, анонимное чтение файлов
отдаёт 200). Один случайный `git add director/` сделал бы капитал, надёжность, работу и
решения владельца читаемыми всему интернету — и git-история этого не забудет.

Поэтому запрет проверяется машиной, а не памятью автора.
"""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cartographer import director_publish as dp  # noqa: E402
from scripts.cartographer import director_server as srv  # noqa: E402

#: Имена и образцы, которых в дереве быть не должно. Каждый — сгенерированный артефакт.
FORBIDDEN_IN_REPO = (
    'director_web_projection.json',
    'freshness_state.json',
    'current.json',
)
FORBIDDEN_GLOBS = (
    'director/*.html',
    'director/*.webmanifest',
    'bundle-*/index.html',
    '**/bundle-2*/*',
)


def _tracked_files():
    """Что git СЧИТАЕТ содержимым репозитория. Рабочее дерево спрашиваем отдельно."""
    out = subprocess.run(['git', '-C', str(ROOT), 'ls-files'],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(f'НЕ ИЗМЕРЕНО: git ls-files отказал: {out.stderr[:200]}')
    return set(out.stdout.split('\n'))


class GeneratedOwnerDataIsNotInTheRepository(unittest.TestCase):

    def test_no_generated_artifact_is_tracked_by_git(self):
        tracked = _tracked_files()
        for name in FORBIDDEN_IN_REPO:
            hits = sorted(p for p in tracked if p.endswith(name))
            self.assertEqual(hits, [], f'сгенерированный артефакт в git: {hits}')

    def test_no_director_bundle_directory_is_tracked(self):
        tracked = _tracked_files()
        hits = sorted(p for p in tracked
                      if p.startswith('director/') or '/bundle-2' in p
                      or p.startswith('bundle-2'))
        self.assertEqual(hits, [], f'каталог комплекта в git: {hits}')

    def test_no_generated_artifact_lies_in_the_working_tree(self):
        """Не только git: файл рядом с кодом однажды окажется в `git add .`."""
        for name in FORBIDDEN_IN_REPO:
            hits = [str(p.relative_to(ROOT)) for p in ROOT.rglob(name)
                    if '.git' not in p.parts]
            self.assertEqual(hits, [], f'сгенерированный артефакт в дереве: {hits}')

    def test_the_bundle_root_is_not_inside_the_repository(self):
        """Корень раздачи обязан жить ВНЕ дерева: иначе он попадёт в доставку."""
        for glob in FORBIDDEN_GLOBS:
            hits = [str(p.relative_to(ROOT)) for p in ROOT.glob(glob)]
            self.assertEqual(hits, [], f'{glob}: {hits}')

    def test_the_publisher_never_writes_into_the_repository(self):
        """Настоящая дыра, найденная этим сторожем 20.09.

        `diff.validate_output` отвечает на другой вопрос — «не попал ли выход внутрь
        НАБЛЮДАЕМОГО набора». Каталог репозитория наблюдаемым набором не является, и
        команда согласилась бы записать комплект прямо в дерево кода.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'snap'
            src.mkdir()
            for target in (ROOT / 'director', ROOT / 'scripts' / 'x', ROOT):
                with self.assertRaises(dp.PublishError) as caught:
                    dp.build_bundle(bundle=src, output=target)
                self.assertIn('публичный', str(caught.exception))

    def test_the_activation_root_may_not_be_inside_the_repository_either(self):
        """Корень раздачи — тоже сгенерированные данные, и тот же запрет."""
        with self.assertRaises(dp.PublishError):
            dp.activate(ROOT / 'director-serve', ROOT / 'scripts', digest='a' * 24)

    def test_the_server_cannot_serve_a_repository_path(self):
        """Сервер знает только имена из таблицы; путь репозитория не адрес."""
        served = {name for name, _ctype in srv.ROUTES.values()}
        self.assertNotIn('CLAUDE.md', served)
        self.assertNotIn('KANBAN.json', served)
        for name in FORBIDDEN_IN_REPO:
            self.assertNotIn(name, served)


class TheSourceCodeItselfCarriesNoPrivateValues(unittest.TestCase):
    """Проверка перед доставкой: в исходниках нет ни секретов, ни личности владельца."""

    FILES = (
        'scripts/cartographer/web_projection.py',
        'scripts/cartographer/web_shell.py',
        'scripts/cartographer/director_publish.py',
        'scripts/cartographer/director_server.py',
        'scripts/agent_director_build.sh',
        'launchd/com.spa.director_build.plist',
        'tests/cartographer/test_web_projection.py',
        'tests/cartographer/test_web_shell.py',
        'tests/cartographer/test_director_publish.py',
        'tests/cartographer/test_director_server.py',
        'tests/cartographer/test_director_delivery_guard.py',
    )

    def _text(self, name):
        return (ROOT / name).read_text(encoding='utf-8')

    def test_no_secret_value_of_any_known_shape(self):
        import re
        shapes = (r'ghp_[A-Za-z0-9]{20,}', r'sk-[A-Za-z0-9]{20,}',
                  r'[0-9]{9,10}:AA[A-Za-z0-9_-]{30,}',
                  r'-----BEGIN [A-Z ]*PRIVATE KEY',
                  r'eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}')
        for name in self.FILES:
            body = self._text(name)
            for shape in shapes:
                self.assertEqual(re.findall(shape, body), [], f'{name}: {shape}')

    def test_no_cloudflare_or_tunnel_token(self):
        import re
        for name in self.FILES:
            body = self._text(name)
            # Имя переменной — не секрет; ЗНАЧЕНИЕ длиной от 40 знаков рядом с ним — да.
            for m in re.finditer(r'(?i)(cloudflare|tunnel|cf)[_-]?(api)?[_-]?token', body):
                tail = body[m.end():m.end() + 80]
                self.assertIsNone(re.search(r'["\'][A-Za-z0-9._-]{40,}["\']', tail),
                                  f'{name}: значение токена рядом с {m.group(0)}')

    def test_no_owner_identity_or_home_path(self):
        """Имя пользователя в путях — это личность владельца в публичном репозитории.

        Исключение объявлено и узко: канонические обёртки launchd обязаны нести
        абсолютный путь прод-дерева, иначе launchd не найдёт цель (это условие самого
        менеджера процессов, а не наш выбор). Для них проверяется только то, что путь
        именно прод-дерева, и ничего больше.

        Искомая строка собирается В КОДЕ — из домашнего каталога текущего пользователя.
        Это ТРЕТИЙ случай одного класса за смену: сторож, написавший запрещённый литерал
        в своём же ассерте, находит себя. Заодно проверка перестаёт быть привязанной к
        одному имени и работает у любого владельца.
        """
        import os
        home_prefix = str(Path(os.path.expanduser('~')))
        wrapper_files = ('scripts/agent_director_build.sh',
                         'launchd/com.spa.director_build.plist')
        for name in self.FILES:
            body = self._text(name)
            if name in wrapper_files:
                for line in body.splitlines():
                    if '/Users/' in line:
                        self.assertIn('/Documents/SPA_Claude', line, f'{name}: {line[:70]}')
                continue
            self.assertNotIn(home_prefix, body, name)

    def test_no_owner_email_or_telegram_id(self):
        import re
        for name in self.FILES:
            body = self._text(name)
            for m in re.finditer(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}', body):
                self.assertIn(m.group(0).split('@')[1], ('example.invalid', 'example.com'),
                              f'{name}: живой адрес {m.group(0)}')
            # Имя собирается в коде: сторож, содержащий искомую строку литералом,
            # находит СЕБЯ. Тот же класс, что и выше, — отравленный корпус.
            owner_var = 'STUDIO_BRIDGE' + '_OWNER_ID'
            self.assertNotIn(owner_var, body, name)

    def test_no_generated_html_or_snapshot_is_embedded_in_the_source(self):
        """Образцы собираются В КОДЕ, а не пишутся литералом.

        Первая редакция содержала искомые строки дословно — и сторож нашёл СЕБЯ.
        Проверка, чей корпус включает её собственный текст, отравлена по построению.
        """
        markers = ('REAL CAPITAL: NOT ' + 'PROVEN</h2>',
                   '"semantic_' + 'digest": "')
        for name in self.FILES:
            body = self._text(name)
            for marker in markers:
                self.assertNotIn(marker, body, f'{name}: {marker[:24]}')

    def test_no_wallet_or_account_identifier(self):
        import re
        for name in self.FILES:
            body = self._text(name)
            # В тестах адреса СИНТЕТИЧЕСКИЕ (0xaaaa… / 0x' + 'a'*40) — они собираются
            # в коде, а не записаны литералом, поэтому литерального адреса быть не должно.
            for m in re.finditer(r'\b0x[a-fA-F0-9]{40}\b', body):
                self.assertRegex(m.group(0), r'0x(([a-f])\2{39}|0{40})',
                                 f'{name}: непохожий на синтетический адрес')


if __name__ == '__main__':
    unittest.main()


class TheBuilderNeverSuggestsPushingGeneratedData(unittest.TestCase):
    """Находка 20.09: команда печатала git-push комплекта — остаток модели Pages.

    При туннельной архитектуре выкладки не существует: раздаётся активированный каталог.
    Печатать строку пуша для сгенерированных владельческих данных в ПУБЛИЧНЫЙ репозиторий
    опасно само по себе — однажды её кто-нибудь выполнит.
    """

    def _source(self):
        return (ROOT / 'scripts/cartographer/director_publish.py').read_text()

    def test_the_pusher_is_not_named_anywhere_in_the_builder(self):
        pusher = 'push_to_' + 'github.py'
        self.assertNotIn(pusher, self._source())

    def test_no_runnable_git_command_is_printed(self):
        """Предмет — ИСПОЛНИМАЯ строка, а не слово «git» в объяснении.

        Первая редакция запрещала само слово и краснела на собственном тексте
        «в git не уходят» — запрет формы вместо запрета действия.
        """
        src = self._source()
        for fragment in ('git add ', 'git commit ', 'git push ', '--files ',
                         'push_to_' + 'github'):
            self.assertNotIn(fragment, src, fragment)

    def test_the_output_says_plainly_that_there_is_no_publish_step(self):
        import io
        import contextlib
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'snap'
            src.mkdir()
            (src / 'investment_snapshot.json').write_text('{"real_capital_proven": false}')
            buf = io.StringIO()
            argv = ['--bundle', str(src), '--output', str(Path(tmp) / 'out')]
            with contextlib.redirect_stdout(buf):
                dp.main(argv)
            out = buf.getvalue()
            self.assertIn('Выкладки в смысле Pages здесь НЕТ', out)
            # Слово «git» в объяснении допустимо и нужно; запрещена ИСПОЛНИМАЯ строка.
            for fragment in ('git add ', 'git push ', '--files ', 'push_to_' + 'github'):
                self.assertNotIn(fragment, out, fragment)
