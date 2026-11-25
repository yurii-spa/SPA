"""ОТВЕРГНУТЫЙ ключ не имеет права быть ХУЖЕ отсутствия ключа (ADR-1095, цикл #1240).

Замер 2026-11-24/25 на живом API при мёртвом `GITHUB_PAT_SPA` — он и есть предмет:

    ось                 МЁРТВЫЙ ключ   БЕЗ ключа
    вердикт прогона     HTTP 401       HTTP 200
    список артефактов   HTTP 401       HTTP 200
    ZIP артефакта       HTTP 401       HTTP 401

Репозиторий публичный, поэтому дверь, цепляющая отвергнутый ключ безусловно, своими
руками превращает публично читаемый ответ в «НЕ ИЗМЕРЕНО: HTTP 401». Цена названа
заказом G1078 п. 2: вердикт прогона `45473114837` простоял НЕ ИЗМЕРЕННЫМ сутки, при
`status=completed` и `conclusion=failure`, читаемых без ключа всё это время.

Каждый тест ниже — положительный контроль: без починки двери краснеет, и краснеет по
НАЗВАННОМУ звену. Сеть инъектирована (`unittest.mock.patch` — восстановление сцены
обеспечено контекстом, а не присваиванием атрибута: `.claude/rules/deployment.md`,
§ «СОСЕД ПО ПРОЦЕССУ»), поэтому тесты отвечают на вопрос «цела ли дверь», а не «что
сегодня у GitHub».
"""

from __future__ import annotations

import io
import json
import unittest
import unittest.mock as mock
import urllib.error

from spa_core.monitoring import record_survival_census as rsc
from spa_core.utils.errors import ConfigError

_PUBLIC = "/repos/yurii-spa/SPA/actions/runs/45473114837"
_ANSWER = {"status": "completed", "conclusion": "failure"}


class _Resp(io.BytesIO):
    """Ответ урла: контекстный менеджер поверх байтов, как у `urlopen`."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        rsc.API_ROOT + _PUBLIC, code, f"код {code}", {}, None)


class _Api:
    """Живой API, заменённый сценой. Пишет, какие заголовки ему предъявили.

    Это несущая часть замера: вопрос «сняла ли дверь ключ на повторе» решается
    ТОЛЬКО по заголовкам ОТДЕЛЬНЫХ попыток, а не по тому, что ответ пришёл.
    """

    def __init__(self, *, with_key, without_key):
        self.with_key, self.without_key = with_key, without_key
        self.calls = []            # [(путь, был ли Authorization)]

    def __call__(self, req, timeout=None):
        authed = "Authorization" in {k.title(): v for k, v in req.headers.items()}
        self.calls.append((req.full_url, authed))
        outcome = self.with_key if authed else self.without_key
        if isinstance(outcome, BaseException):
            raise outcome
        return _Resp(json.dumps(outcome).encode("utf-8"))

    @property
    def authed_calls(self):
        return [c for c in self.calls if c[1]]

    @property
    def anon_calls(self):
        return [c for c in self.calls if not c[1]]


class GithubDoorTest(unittest.TestCase):

    def _door(self, api, *, token="мёртвый-ключ"):
        """Дверь на инъектированной сети. Токен — ВХОД, а не Связка ключей."""
        patch = mock.patch.object(rsc.urllib.request, "urlopen", api)
        patch.start()
        self.addCleanup(patch.stop)
        return rsc.github_fetch(token)

    # ─────────── ось 1: ключ ОТВЕРГНУТ, ресурс публичен ───────────

    def test_a_rejected_key_does_not_lose_a_public_answer(self):
        """401 по ключу + 200 анонимно ⇒ ОТВЕТ, а не «НЕ ИЗМЕРЕНО».

        Без починки здесь поднимается `HTTPError` — ровно то, что сутки читалось как
        «вердикт не измерен».
        """
        api = _Api(with_key=_http_error(401), without_key=_ANSWER)
        fetch = self._door(api)
        self.assertEqual(fetch(_PUBLIC), _ANSWER)

    def test_a_forbidden_key_is_also_a_rejected_key(self):
        """403 — тот же предмет: ключ предъявлен и не принят."""
        api = _Api(with_key=_http_error(403), without_key=_ANSWER)
        self.assertEqual(self._door(api)(_PUBLIC), _ANSWER)

    def test_the_retry_carries_no_key(self):
        """Повтор обязан идти БЕЗ заголовка авторизации — это и есть механизм.

        Проверяется по заголовкам попыток: ответ мог бы прийти и от двери, которая
        ключ оставила, и тогда зелёный тест не говорил бы ни о чём.
        """
        api = _Api(with_key=_http_error(401), without_key=_ANSWER)
        self._door(api)(_PUBLIC)
        self.assertEqual(len(api.authed_calls), 1, api.calls)
        self.assertEqual(len(api.anon_calls), 1, api.calls)

    def test_the_retry_happens_exactly_once(self):
        """Один повтор, а не буря: дверь не долбит API на каждом отказе."""
        api = _Api(with_key=_http_error(401), without_key=_http_error(401))
        with self.assertRaises(ConfigError):
            self._door(api)(_PUBLIC)
        self.assertEqual(len(api.calls), 2, api.calls)

    # ─────────── ось 2: ТРИ исхода различимы (инв. #17) ───────────

    def test_the_door_that_answered_is_recorded(self):
        """«Ответил ключ» и «ответила публичная ось» — РАЗНЫЕ утверждения."""
        api = _Api(with_key=_http_error(401), without_key=_ANSWER)
        fetch = self._door(api)
        fetch(_PUBLIC)
        self.assertEqual(fetch.door, rsc.DOOR_ANONYMOUS)
        self.assertEqual(fetch.key_rejected, "HTTP 401")
        self.assertEqual(fetch.anonymous_paths, [_PUBLIC])

    def test_a_healthy_key_is_not_reported_as_anonymous(self):
        """Обратная половина: здоровый ключ НЕ красится анонимным.

        Без неё «дверь всегда говорит anonymous» прошло бы незамеченным.
        """
        api = _Api(with_key=_ANSWER, without_key=_http_error(401))
        fetch = self._door(api)
        self.assertEqual(fetch(_PUBLIC), _ANSWER)
        self.assertEqual(fetch.door, rsc.DOOR_BY_KEY)
        self.assertIsNone(fetch.key_rejected)
        self.assertEqual(fetch.anonymous_paths, [])
        self.assertEqual(len(api.anon_calls), 0, api.calls)

    def test_an_unasked_door_is_not_a_healthy_key(self):
        """До первого чтения дверь — `None`, а не «ответил ключ»."""
        fetch = self._door(_Api(with_key=_ANSWER, without_key=_ANSWER))
        self.assertIsNone(fetch.door)

    def test_both_doors_failing_names_both_attempts(self):
        """ZIP-случай: 401 и по ключу, и анонимно ⇒ НЕ ИЗМЕРЕНО с ДВУМЯ причинами.

        Назвать одну значило бы либо скрыть, что ключ отвергнут, либо выдать приватный
        ресурс за сбой ключа.
        """
        api = _Api(with_key=_http_error(401), without_key=_http_error(401))
        with self.assertRaises(ConfigError) as box:
            self._door(api)(_PUBLIC)
        said = str(box.exception)
        self.assertIn("по ключу HTTP 401", said)
        self.assertIn("анонимно", said)

    # ─────────── ось 3: чужие отказы НЕ маскируются ───────────

    def test_a_404_is_not_retried_anonymously(self):
        """`404` не про ключ: повтор ответил бы на другой вопрос и мог бы ЗАМАЗАТЬ его.

        Положительный контроль на переобобщение починки.
        """
        api = _Api(with_key=_http_error(404), without_key=_ANSWER)
        with self.assertRaises(urllib.error.HTTPError) as box:
            self._door(api)(_PUBLIC)
        self.assertEqual(box.exception.code, 404)
        self.assertEqual(len(api.anon_calls), 0, api.calls)

    def test_a_server_error_is_not_retried_anonymously(self):
        api = _Api(with_key=_http_error(500), without_key=_ANSWER)
        with self.assertRaises(urllib.error.HTTPError):
            self._door(api)(_PUBLIC)
        self.assertEqual(len(api.anon_calls), 0, api.calls)

    def test_the_rejected_codes_are_declared_not_inlined(self):
        """Перечень кодов отказа — ОБЪЯВЛЕН, иначе он разойдётся с тестом молча."""
        self.assertEqual(tuple(sorted(rsc.KEY_REJECTED_CODES)), (401, 403))

    # ─────────── ось 4: выбор двери ПЕЧАТАЕТСЯ ───────────

    def test_the_anonymous_choice_is_printed_to_stderr(self):
        """Молча подставить анонимный ответ хуже ошибки: отзыв прав выглядел бы
        здоровьем. Печать — в `stderr`, чтобы не попасть в `--json` на `stdout`."""
        api = _Api(with_key=_http_error(401), without_key=_ANSWER)
        fetch = self._door(api)
        err, out = io.StringIO(), io.StringIO()
        with mock.patch("sys.stderr", err), mock.patch("sys.stdout", out):
            fetch(_PUBLIC)
        self.assertIn("ОТВЕРГНУТ", err.getvalue())
        self.assertIn("АНОНИМНО", err.getvalue())
        self.assertEqual(out.getvalue(), "")

    def test_a_healthy_key_prints_nothing(self):
        api = _Api(with_key=_ANSWER, without_key=_ANSWER)
        fetch = self._door(api)
        err = io.StringIO()
        with mock.patch("sys.stderr", err):
            fetch(_PUBLIC)
        self.assertEqual(err.getvalue(), "")

    # ─────────── ось 5: прежний контракт НЕ ослаблен (инв. #16) ───────────

    def test_an_absent_token_is_still_a_refusal(self):
        """Отсутствие ключа остаётся ИСКЛЮЧЕНИЕМ, а не анонимным чтением.

        Контракт закреплён сторожами `test_ci_control_verdict_wiring.py`
        (`test_an_absent_token_is_unmeasured_not_green`, код возврата 2); полный вердикт
        требует ZIP, который без ключа неизмерим, поэтому менять его эта починка права
        не имеет.
        """
        with mock.patch.dict("os.environ", {"GITHUB_TOKEN": "", "GITHUB_PAT_SPA": ""},
                             clear=False), \
             mock.patch.object(rsc, "_token_from_keychain", lambda: None):
            with self.assertRaises(ConfigError):
                rsc.github_fetch()


if __name__ == "__main__":
    unittest.main()
