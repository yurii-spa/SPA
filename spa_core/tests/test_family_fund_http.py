"""
Тесты для spa_core/family_fund/http_server.py (MP-359)

Структура:
  TestCheckToken          — 6 тестов чистой функции check_token
  TestNowIso              — 2 теста вспомогательной функции _now_iso
  TestLoadPaperStatus     — 3 теста _load_paper_status
  TestBuildSummary        — 8 тестов build_summary
  TestBuildInvestors      — 5 тестов build_investors_response
  TestFundHTTPIntegration — 21 интеграционный тест через живой сервер
  ─────────────────────────────────────────────────────────────────
  Итого: 45+ тестов

Запуск:
  python3 -m pytest spa_core/tests/test_family_fund_http.py -q
"""
from __future__ import annotations

import http.client
import json
import os
import shutil
import socket
import socketserver
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Импорт тестируемых объектов
# ---------------------------------------------------------------------------

from spa_core.family_fund.http_server import (
    _now_iso,
    _load_paper_status,
    check_token,
    build_summary,
    build_investors_response,
    make_handler_class,
)
from spa_core.family_fund.models import Investor
from spa_core.family_fund.registry import InvestorRegistry


# ---------------------------------------------------------------------------
# Вспомогательные утилиты для интеграционных тестов
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    """Находит свободный порт на localhost (bind + release)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ReusableTCPServer(socketserver.TCPServer):
    """TCPServer с SO_REUSEADDR для тестов."""
    allow_reuse_address = True


def _http_get(
    port: int,
    path: str,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, dict, http.client.HTTPResponse]:
    """
    Выполняет GET-запрос к локальному серверу.
    Возвращает (status_code, body_as_dict, raw_response).
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers=headers or {})
    resp = conn.getresponse()
    body_bytes = resp.read()
    conn.close()
    body = json.loads(body_bytes.decode("utf-8"))
    return resp.status, body, resp


def _http_post(
    port: int,
    path: str,
    payload: dict,
    headers: Optional[Dict[str, str]] = None,
    raw_body: Optional[bytes] = None,
) -> Tuple[int, dict]:
    """
    Выполняет POST-запрос к локальному серверу.
    Возвращает (status_code, body_as_dict).
    """
    if raw_body is not None:
        body_bytes = raw_body
    else:
        body_bytes = json.dumps(payload).encode("utf-8")

    h: Dict[str, str] = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body_bytes)),
    }
    h.update(headers or {})

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", path, body=body_bytes, headers=h)
    resp = conn.getresponse()
    body = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return resp.status, body


def _make_investor(
    inv_id: str = "u1",
    name: str = "Alice",
    email: str = "alice@example.com",
    initial_capital: float = 10000.0,
    share_pct: float = 100.0,
    status: str = "active",
) -> Investor:
    """Создаёт тестового инвестора."""
    return Investor(
        id=inv_id,
        name=name,
        email=email,
        wallet_address="0xABCDEF",
        joined_at="2026-06-01T00:00:00Z",
        initial_capital_usd=initial_capital,
        current_share_pct=share_pct,
        status=status,
    )


# ===========================================================================
# TestCheckToken — 6 тестов
# ===========================================================================

class TestCheckToken(unittest.TestCase):
    """Тесты чистой функции check_token (без HTTP)."""

    def setUp(self) -> None:
        """Сохраняем и убираем переменную окружения перед каждым тестом."""
        self._orig = os.environ.pop("SPA_FUND_TOKEN", None)

    def tearDown(self) -> None:
        """Восстанавливаем переменную окружения после теста."""
        if self._orig is not None:
            os.environ["SPA_FUND_TOKEN"] = self._orig
        else:
            os.environ.pop("SPA_FUND_TOKEN", None)

    def test_valid_token_returns_true(self) -> None:
        os.environ["SPA_FUND_TOKEN"] = "my-secret"
        self.assertTrue(check_token("my-secret"))

    def test_invalid_token_returns_false(self) -> None:
        os.environ["SPA_FUND_TOKEN"] = "my-secret"
        self.assertFalse(check_token("wrong-value"))

    def test_empty_env_always_returns_false(self) -> None:
        """Если токен не настроен — любой запрос отклоняется."""
        os.environ["SPA_FUND_TOKEN"] = ""
        self.assertFalse(check_token("anything"))

    def test_none_token_returns_false(self) -> None:
        """None вместо токена (заголовок отсутствует) → False."""
        os.environ["SPA_FUND_TOKEN"] = "my-secret"
        self.assertFalse(check_token(None))

    def test_missing_env_returns_false(self) -> None:
        """SPA_FUND_TOKEN не задан совсем → False."""
        os.environ.pop("SPA_FUND_TOKEN", None)
        self.assertFalse(check_token("anything"))

    def test_comparison_is_case_sensitive(self) -> None:
        """Сравнение регистрозависимое: 'Secret' ≠ 'secret'."""
        os.environ["SPA_FUND_TOKEN"] = "Secret"
        self.assertFalse(check_token("secret"))


# ===========================================================================
# TestNowIso — 2 теста
# ===========================================================================

class TestNowIso(unittest.TestCase):
    """Тесты вспомогательной функции _now_iso."""

    def test_timestamp_is_parseable_iso_format(self) -> None:
        """Результат _now_iso() должен парситься без исключений."""
        ts = _now_iso()
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        self.assertIsNotNone(dt)

    def test_timestamp_ends_with_z(self) -> None:
        """ISO 8601 UTC — должен заканчиваться на 'Z'."""
        self.assertTrue(_now_iso().endswith("Z"))


# ===========================================================================
# TestLoadPaperStatus — 3 теста
# ===========================================================================

class TestLoadPaperStatus(unittest.TestCase):
    """Тесты _load_paper_status — чтение paper_trading_status.json."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def test_missing_file_returns_empty_dict(self) -> None:
        result = _load_paper_status(self.tmp_dir)
        self.assertEqual(result, {})

    def test_existing_file_is_loaded(self) -> None:
        data = {"current_equity": 99_000.0, "apy_today_pct": 3.5}
        (self.tmp_dir / "paper_trading_status.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        result = _load_paper_status(self.tmp_dir)
        self.assertAlmostEqual(result["current_equity"], 99_000.0)

    def test_loaded_dict_has_correct_types(self) -> None:
        data = {"is_demo": False, "days_running": 10}
        (self.tmp_dir / "paper_trading_status.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        result = _load_paper_status(self.tmp_dir)
        self.assertIsInstance(result["days_running"], int)


# ===========================================================================
# TestBuildSummary — 8 тестов
# ===========================================================================

class TestBuildSummary(unittest.TestCase):
    """Тесты функции build_summary."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.registry = InvestorRegistry(
            investors_path=self.tmp_dir / "investors.json"
        )

    def tearDown(self) -> None:
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def _write_status(self, data: dict) -> None:
        (self.tmp_dir / "paper_trading_status.json").write_text(
            json.dumps(data), encoding="utf-8"
        )

    def test_empty_dir_returns_all_required_keys(self) -> None:
        summary = build_summary(self.tmp_dir, self.registry)
        required = {"aum_usd", "num_investors", "current_apy",
                    "paper_days", "status", "last_cycle"}
        self.assertTrue(required.issubset(summary.keys()))

    def test_status_field_is_paper_trading(self) -> None:
        summary = build_summary(self.tmp_dir, self.registry)
        self.assertEqual(summary["status"], "paper_trading")

    def test_aum_from_current_equity(self) -> None:
        self._write_status({"current_equity": 123_456.78})
        summary = build_summary(self.tmp_dir, self.registry)
        self.assertAlmostEqual(summary["aum_usd"], 123_456.78, places=2)

    def test_apy_converted_from_percent_to_fraction(self) -> None:
        """apy_today_pct=3.196 → current_apy≈0.03196."""
        self._write_status({"apy_today_pct": 3.196})
        summary = build_summary(self.tmp_dir, self.registry)
        self.assertAlmostEqual(summary["current_apy"], 0.03196, places=5)

    def test_default_apy_when_zero(self) -> None:
        """apy_today_pct=0 → fallback 0.032 (3.2%)."""
        self._write_status({"apy_today_pct": 0.0})
        summary = build_summary(self.tmp_dir, self.registry)
        self.assertEqual(summary["current_apy"], 0.032)

    def test_paper_days_from_days_running_field(self) -> None:
        self._write_status({"days_running": 42})
        summary = build_summary(self.tmp_dir, self.registry)
        self.assertEqual(summary["paper_days"], 42)

    def test_num_investors_counts_registry(self) -> None:
        inv1 = _make_investor("i1", "Alice", "a@x.com", 50000.0, 50.0)
        inv2 = _make_investor("i2", "Bob", "b@x.com", 50000.0, 50.0)
        self.registry.save([inv1, inv2])
        summary = build_summary(self.tmp_dir, self.registry)
        self.assertEqual(summary["num_investors"], 2)

    def test_num_investors_zero_when_no_registry_file(self) -> None:
        """При отсутствии investors.json — num_investors=0."""
        summary = build_summary(self.tmp_dir, self.registry)
        self.assertEqual(summary["num_investors"], 0)


# ===========================================================================
# TestBuildInvestors — 5 тестов
# ===========================================================================

class TestBuildInvestors(unittest.TestCase):
    """Тесты функции build_investors_response."""

    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.registry = InvestorRegistry(
            investors_path=self.tmp_dir / "investors.json"
        )

    def tearDown(self) -> None:
        shutil.rmtree(str(self.tmp_dir), ignore_errors=True)

    def _write_equity(self, equity: float) -> None:
        (self.tmp_dir / "paper_trading_status.json").write_text(
            json.dumps({"current_equity": equity}), encoding="utf-8"
        )

    def test_empty_registry_returns_empty_list(self) -> None:
        result = build_investors_response(self.registry, self.tmp_dir)
        self.assertEqual(result, [])

    def test_response_contains_required_fields(self) -> None:
        self.registry.save([_make_investor()])
        result = build_investors_response(self.registry, self.tmp_dir)
        r = result[0]
        for field in ("id", "name", "email", "pnl_usd",
                      "current_share_pct", "initial_capital_usd", "status"):
            self.assertIn(field, r, f"Поле {field!r} отсутствует")

    def test_pnl_positive_when_gain(self) -> None:
        """initial=10000, equity=11000, share=100% → pnl=+1000."""
        self.registry.save([_make_investor(initial_capital=10_000.0, share_pct=100.0)])
        self._write_equity(11_000.0)
        result = build_investors_response(self.registry, self.tmp_dir)
        self.assertAlmostEqual(result[0]["pnl_usd"], 1_000.0, places=2)

    def test_pnl_negative_when_loss(self) -> None:
        """initial=10000, equity=9000, share=100% → pnl=-1000."""
        self.registry.save([_make_investor(initial_capital=10_000.0, share_pct=100.0)])
        self._write_equity(9_000.0)
        result = build_investors_response(self.registry, self.tmp_dir)
        self.assertAlmostEqual(result[0]["pnl_usd"], -1_000.0, places=2)

    def test_multiple_investors_proportional_pnl(self) -> None:
        """Два инвестора по 50% — каждый получает половину прироста."""
        inv1 = _make_investor("i1", "A", "a@x.com", 5_000.0, 50.0)
        inv2 = _make_investor("i2", "B", "b@x.com", 5_000.0, 50.0)
        self.registry.save([inv1, inv2])
        self._write_equity(12_000.0)  # прирост $2000 (по $1000 каждому)
        result = build_investors_response(self.registry, self.tmp_dir)
        pnl_a = next(r["pnl_usd"] for r in result if r["name"] == "A")
        pnl_b = next(r["pnl_usd"] for r in result if r["name"] == "B")
        self.assertAlmostEqual(pnl_a, 1_000.0, places=1)
        self.assertAlmostEqual(pnl_b, 1_000.0, places=1)


# ===========================================================================
# TestFundHTTPIntegration — 21 тест (живой сервер через http.client)
# ===========================================================================

class TestFundHTTPIntegration(unittest.TestCase):
    """
    Интеграционные тесты через живой TCPServer на случайном порту.
    Сервер стартует один раз в setUpClass, останавливается в tearDownClass.
    """

    _server: Optional[_ReusableTCPServer] = None
    _thread: Optional[threading.Thread] = None
    _port: int = 0
    _tmp_dir: Optional[Path] = None
    _TOKEN = "integration-test-token-xyz"

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_dir = Path(tempfile.mkdtemp())
        cls._port = _find_free_port()
        os.environ["SPA_FUND_TOKEN"] = cls._TOKEN

        handler_cls = make_handler_class(cls._tmp_dir)
        cls._server = _ReusableTCPServer(("127.0.0.1", cls._port), handler_cls)
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        # Даём серверу время подняться
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._server:
            cls._server.shutdown()
        if cls._tmp_dir:
            shutil.rmtree(str(cls._tmp_dir), ignore_errors=True)
        os.environ.pop("SPA_FUND_TOKEN", None)

    # --------------------------------------------------------------------- #
    # GET /health
    # --------------------------------------------------------------------- #

    def test_health_returns_200(self) -> None:
        code, _, _ = _http_get(self._port, "/health")
        self.assertEqual(code, 200)

    def test_health_body_status_is_ok(self) -> None:
        _, body, _ = _http_get(self._port, "/health")
        self.assertEqual(body.get("status"), "ok")

    def test_health_body_has_timestamp_field(self) -> None:
        _, body, _ = _http_get(self._port, "/health")
        self.assertIn("timestamp", body)

    def test_health_timestamp_is_valid_iso(self) -> None:
        _, body, _ = _http_get(self._port, "/health")
        # strptime бросит ValueError при неверном формате
        datetime.strptime(body["timestamp"], "%Y-%m-%dT%H:%M:%SZ")

    # --------------------------------------------------------------------- #
    # GET /api/public/fund/summary
    # --------------------------------------------------------------------- #

    def test_public_summary_returns_200(self) -> None:
        code, _, _ = _http_get(self._port, "/api/public/fund/summary")
        self.assertEqual(code, 200)

    def test_public_summary_has_all_required_fields(self) -> None:
        _, body, _ = _http_get(self._port, "/api/public/fund/summary")
        for key in ("aum_usd", "num_investors", "current_apy",
                    "paper_days", "status", "last_cycle"):
            self.assertIn(key, body, f"Поле {key!r} отсутствует")

    def test_public_summary_status_equals_paper_trading(self) -> None:
        _, body, _ = _http_get(self._port, "/api/public/fund/summary")
        self.assertEqual(body["status"], "paper_trading")

    def test_public_summary_cors_header_is_wildcard(self) -> None:
        """Публичные эндпоинты должны отдавать Access-Control-Allow-Origin: *."""
        conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=5)
        conn.request("GET", "/api/public/fund/summary")
        resp = conn.getresponse()
        resp.read()
        cors = resp.getheader("Access-Control-Allow-Origin")
        conn.close()
        self.assertEqual(cors, "*")

    def test_public_summary_content_type_is_json(self) -> None:
        conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=5)
        conn.request("GET", "/api/public/fund/summary")
        resp = conn.getresponse()
        resp.read()
        ct = resp.getheader("Content-Type", "")
        conn.close()
        self.assertIn("application/json", ct)

    # --------------------------------------------------------------------- #
    # GET /api/private/investors
    # --------------------------------------------------------------------- #

    def test_private_investors_no_token_returns_401(self) -> None:
        code, _, _ = _http_get(self._port, "/api/private/investors")
        self.assertEqual(code, 401)

    def test_private_investors_wrong_token_returns_401(self) -> None:
        code, _, _ = _http_get(
            self._port, "/api/private/investors",
            headers={"X-Fund-Token": "totally-wrong-token"}
        )
        self.assertEqual(code, 401)

    def test_private_investors_valid_token_returns_200(self) -> None:
        code, _, _ = _http_get(
            self._port, "/api/private/investors",
            headers={"X-Fund-Token": self._TOKEN}
        )
        self.assertEqual(code, 200)

    def test_private_investors_returns_list_type(self) -> None:
        _, body, _ = _http_get(
            self._port, "/api/private/investors",
            headers={"X-Fund-Token": self._TOKEN}
        )
        self.assertIsInstance(body, list)

    def test_private_investors_no_cors_header(self) -> None:
        """Приватные эндпоинты не должны иметь CORS-заголовок."""
        conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=5)
        conn.request(
            "GET", "/api/private/investors",
            headers={"X-Fund-Token": self._TOKEN}
        )
        resp = conn.getresponse()
        resp.read()
        cors = resp.getheader("Access-Control-Allow-Origin")
        conn.close()
        self.assertIsNone(cors)

    # --------------------------------------------------------------------- #
    # 404
    # --------------------------------------------------------------------- #

    def test_unknown_get_path_returns_404(self) -> None:
        code, _, _ = _http_get(self._port, "/no-such-endpoint")
        self.assertEqual(code, 404)

    def test_unknown_get_path_body_has_error_key(self) -> None:
        _, body, _ = _http_get(self._port, "/unknown/path")
        self.assertIn("error", body)

    # --------------------------------------------------------------------- #
    # POST /api/private/investor
    # --------------------------------------------------------------------- #

    def test_post_investor_no_token_returns_401(self) -> None:
        code, _ = _http_post(
            self._port, "/api/private/investor",
            payload={"name": "X", "email": "x@x.com",
                     "wallet": "0x1", "initial_capital_usd": 1000}
        )
        self.assertEqual(code, 401)

    def test_post_investor_wrong_token_returns_401(self) -> None:
        code, _ = _http_post(
            self._port, "/api/private/investor",
            payload={"name": "X", "email": "x@x.com",
                     "wallet": "0x1", "initial_capital_usd": 1000},
            headers={"X-Fund-Token": "bad-token"}
        )
        self.assertEqual(code, 401)

    def test_post_investor_missing_fields_returns_400(self) -> None:
        """Отсутствуют email, wallet, initial_capital_usd → 400."""
        code, _ = _http_post(
            self._port, "/api/private/investor",
            payload={"name": "OnlyName"},
            headers={"X-Fund-Token": self._TOKEN}
        )
        self.assertEqual(code, 400)

    def test_post_investor_valid_payload_returns_201(self) -> None:
        code, body = _http_post(
            self._port, "/api/private/investor",
            payload={
                "name": "Charlie",
                "email": "charlie@test.com",
                "wallet": "0xDEADBEEF",
                "initial_capital_usd": 25_000.0,
            },
            headers={"X-Fund-Token": self._TOKEN}
        )
        self.assertEqual(code, 201)
        self.assertIn("id", body)

    def test_post_investor_response_has_correct_name(self) -> None:
        code, body = _http_post(
            self._port, "/api/private/investor",
            payload={
                "name": "Dana",
                "email": "dana@test.com",
                "wallet": "0xCAFE",
                "initial_capital_usd": 5_000.0,
            },
            headers={"X-Fund-Token": self._TOKEN}
        )
        self.assertEqual(code, 201)
        self.assertEqual(body["name"], "Dana")

    def test_post_investor_status_is_pending(self) -> None:
        _, body = _http_post(
            self._port, "/api/private/investor",
            payload={
                "name": "Eve",
                "email": "eve@test.com",
                "wallet": "0xEEE",
                "initial_capital_usd": 8_000.0,
            },
            headers={"X-Fund-Token": self._TOKEN}
        )
        self.assertEqual(body["status"], "pending")

    def test_post_investor_appears_in_get_list(self) -> None:
        """После POST инвестор должен появиться в GET /api/private/investors."""
        unique_name = "Frank_Unique_12345"
        _http_post(
            self._port, "/api/private/investor",
            payload={
                "name": unique_name,
                "email": "frank@test.com",
                "wallet": "0xFFF",
                "initial_capital_usd": 3_000.0,
            },
            headers={"X-Fund-Token": self._TOKEN}
        )
        _, investors, _ = _http_get(
            self._port, "/api/private/investors",
            headers={"X-Fund-Token": self._TOKEN}
        )
        names = [i["name"] for i in investors]
        self.assertIn(unique_name, names)

    def test_post_invalid_json_returns_400(self) -> None:
        """Невалидный JSON в теле → 400."""
        code, _ = _http_post(
            self._port, "/api/private/investor",
            payload={},
            raw_body=b"not-valid-json{{{",
            headers={"X-Fund-Token": self._TOKEN}
        )
        self.assertEqual(code, 400)

    def test_post_empty_body_returns_400(self) -> None:
        """Content-Length: 0 → 400."""
        conn = http.client.HTTPConnection("127.0.0.1", self._port, timeout=5)
        conn.request(
            "POST", "/api/private/investor",
            body=b"",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "0",
                "X-Fund-Token": self._TOKEN,
            }
        )
        resp = conn.getresponse()
        code = resp.status
        resp.read()
        conn.close()
        self.assertEqual(code, 400)

    def test_post_to_unknown_path_returns_404(self) -> None:
        code, _ = _http_post(
            self._port, "/api/unknown/endpoint",
            payload={},
            headers={"X-Fund-Token": self._TOKEN}
        )
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
