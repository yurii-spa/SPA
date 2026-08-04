"""
MP-443: Tests for scripts/fund_api_server.py
Запуск: python3 -m pytest tests/test_fund_api.py -v
         -- или --
         python3 -m unittest tests.test_fund_api -v

Используется только stdlib (http.client, unittest, threading, json, tempfile, os).

**Порт здесь НИКОГДА не задаётся константой** (карточка `agent-fund-api-tests-bind-a-fixed-port`).
Сервер поднимается по-настоящему, а раньше он биндил жёстко зашитые 18765/18766. Два pytest'а на
одном хосте дрались за эти порты, и проигравший получал `OSError: [Errno 48] Address already in
use`. Бьёт это не по продукту, а по МЕТОДИКЕ приёмки автономных циклов, где worktree и контроль на
чистом `origin/main` гоняются ПАРАЛЛЕЛЬНО: измерено на неисправленном дереве — один прогон дал
`1 passed, 8 errors`, второй `8 passed, 1 error`, то есть «дельта passed» между сторонами зависела
от того, кто первым добежал до этого файла. Теперь порт запрашивает ядро (`bind` на 0), а
фактический номер читается у уже поднятого сервера. Пин против рецидива — `EphemeralPortTestCase`.
"""

import http.client
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

# Добавляем корень проекта в sys.path, чтобы импортировать fund_api_server
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import scripts.fund_api_server as api_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_server(data_dir: str):
    """Запускает сервер на СВОБОДНОМ порту в daemon-потоке.

    Возвращает поток с атрибутами ``.server`` (для shutdown/close) и ``.port`` — фактическим
    номером, прочитанным у уже забиндившегося сокета. Порт не принимается аргументом намеренно:
    пока его можно было назвать, его называли константой (см. докстринг модуля).

    ``allow_reuse_address`` здесь больше не выставляется: ``HTTPServer`` включает его сам, а
    прежнее присвоение шло ПОСЛЕ конструктора, то есть уже после ``bind`` — оно не могло ни на
    что повлиять и лишь создавало впечатление, будто конфликт портов чем-то обработан.
    """
    # Переопределяем DATA_DIR модуля для текущего экземпляра
    api_module.DATA_DIR = Path(data_dir)

    # Порт 0 = «дай любой свободный»; настоящий номер известен только после bind.
    server = http.server.HTTPServer(("127.0.0.1", 0), api_module.FundAPIHandler)

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.server = server  # сохраняем ссылку для shutdown
    t.port = server.server_address[1]
    t.start()
    time.sleep(0.3)  # даём серверу подняться
    return t


def _stop_server(thread):
    """Останавливает цикл обслуживания И закрывает слушающий сокет.

    ``shutdown()`` только выводит ``serve_forever`` из цикла — сокет остаётся забинденным до
    ``server_close()``. Прежний код звал лишь ``shutdown()``, поэтому каждый прогон оставлял за
    собой занятые сокеты; на фиксированном порту это ещё и продлевало ровно ту гонку, из-за
    которой карточка и заведена.
    """
    thread.server.shutdown()
    thread.server.server_close()


import http.server as _http_server
import tempfile


class FundAPITestCase(unittest.TestCase):
    """8 тестов для Fund API Server (без внешних зависимостей)."""

    tmp_dir: tempfile.TemporaryDirectory
    server_thread: threading.Thread
    conn: http.client.HTTPConnection

    @classmethod
    def setUpClass(cls):
        # Создаём временную папку с тестовыми JSON-данными
        cls.tmp_dir = tempfile.TemporaryDirectory()
        data_dir = cls.tmp_dir.name

        # Записываем минимальные fixture-файлы
        fixtures = {
            "golive_status.json": {
                "ready": False,
                "checks": {"equity_curve_real": True},
                "blockers": ["demo_data"],
                "timestamp": "2026-06-12T00:00:00Z",
                "source": "test",
            },
            "tournament_ranking.json": {
                "generated_at": "2026-06-12",
                "winner": "S1",
                "strategies": [
                    {"rank": 1, "id": "S1", "name": "Test Strategy", "composite_score": 0.9}
                ],
            },
            "adapter_status.json": {
                "generated_at": "2026-06-12T00:00:00Z",
                "schema_version": 1,
                "execution_mode": "dry_run",
                "adapters": [],
            },
            "paper_evidence.json": {
                "schema_version": "1.0",
                "start_date": "2026-06-12",
                "min_days_required": 30,
                "days": [],
            },
            "paper_trading_status.json": {
                "is_demo": False,
                "days_running": 2,
                "current_equity": 100020.0,
                "total_return_pct": 0.02,
                "apy_today_pct": 3.5,
                "daily_yield_usd": 9.5,
                "kill_switch_active": False,
                "last_cycle_ts": "2026-06-12T06:00:00Z",
                "last_cycle_status": "ok",
                "paper_start_date": "2026-06-10",
            },
            "equity_curve_daily.json": {
                "summary": {
                    "start_equity": 100000.0,
                    "end_equity": 100020.0,
                    "max_drawdown_pct": 0.0,
                    "positive_days": 2,
                    "negative_days": 0,
                    "num_days": 2,
                    "first_date": "2026-06-10",
                    "last_date": "2026-06-12",
                },
                "daily": [],
            },
            "current_positions.json": {
                "is_demo": False,
                "capital_usd": 100000.0,
                "deployed_usd": 95000.0,
                "cash_usd": 5000.0,
                "positions": {"aave_v3": 50000.0, "compound_v3": 45000.0},
            },
            "gap_monitor.json": {
                "gap_count": 0,
                "last_check": "2026-06-12",
            },
        }

        for fname, data in fixtures.items():
            fpath = os.path.join(data_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(data, f)

        # Стартуем сервер
        cls.server_thread = _start_server(data_dir)
        cls.conn = http.client.HTTPConnection("127.0.0.1", cls.server_thread.port, timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        _stop_server(cls.server_thread)
        cls.tmp_dir.cleanup()

    # ---------- утилита ----------

    def _get(self, path: str):
        """Делает GET запрос и возвращает (status, headers, body_dict)."""
        self.conn.request("GET", path)
        resp = self.conn.getresponse()
        body = resp.read()
        data = json.loads(body.decode("utf-8"))
        return resp.status, dict(resp.getheaders()), data

    # ===========================
    # Test 1: /health → 200 + status ok
    # ===========================
    def test_01_health_returns_ok(self):
        status, _, data = self._get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertIn("timestamp", data)

    # ===========================
    # Test 2: CORS header присутствует
    # ===========================
    def test_02_cors_header_present(self):
        _, headers, _ = self._get("/health")
        # HTTP заголовки в http.client возвращаются в нижнем регистре
        headers_lower = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(headers_lower.get("access-control-allow-origin"), "*")

    # ===========================
    # Test 3: /api/fund/summary содержит ключевые поля
    # ===========================
    def test_03_summary_has_required_fields(self):
        status, _, data = self._get("/api/fund/summary")
        self.assertEqual(status, 200)
        self.assertIn("fund", data)
        self.assertIn("equity", data)
        self.assertIn("positions", data)
        self.assertIn("golive", data)
        self.assertIn("generated_at", data)

    # ===========================
    # Test 4: /api/fund/summary — данные корректные
    # ===========================
    def test_04_summary_data_correct(self):
        _, _, data = self._get("/api/fund/summary")
        self.assertFalse(data["fund"]["is_demo"])
        self.assertEqual(data["fund"]["days_running"], 2)
        self.assertAlmostEqual(data["fund"]["current_equity_usd"], 100020.0)
        self.assertEqual(data["equity"]["positive_days"], 2)
        self.assertAlmostEqual(data["positions"]["cash_usd"], 5000.0)

    # ===========================
    # Test 5: /api/fund/strategies → tournament data
    # ===========================
    def test_05_strategies_returns_tournament(self):
        status, _, data = self._get("/api/fund/strategies")
        self.assertEqual(status, 200)
        self.assertEqual(data["winner"], "S1")
        self.assertIsInstance(data["strategies"], list)
        self.assertEqual(len(data["strategies"]), 1)
        self.assertEqual(data["strategies"][0]["id"], "S1")

    # ===========================
    # Test 6: /api/fund/adapters → adapter_status
    # ===========================
    def test_06_adapters_returns_adapter_status(self):
        status, _, data = self._get("/api/fund/adapters")
        self.assertEqual(status, 200)
        self.assertEqual(data["execution_mode"], "dry_run")
        self.assertIn("adapters", data)

    # ===========================
    # Test 7: /api/fund/golive → golive_status
    # ===========================
    def test_07_golive_returns_status(self):
        status, _, data = self._get("/api/fund/golive")
        self.assertEqual(status, 200)
        self.assertIn("ready", data)
        self.assertIn("blockers", data)
        self.assertFalse(data["ready"])
        self.assertIn("demo_data", data["blockers"])

    # ===========================
    # Test 8: несуществующий файл → 200 + error sentinel
    # ===========================
    def test_08_missing_file_returns_sentinel(self):
        # Подменяем evidence file — удалим и запросим
        evidence_path = os.path.join(api_module.DATA_DIR, "paper_evidence_missing.json")
        # Запрашиваем несуществующий эндпоинт — 404
        status, _, data = self._get("/api/fund/nonexistent")
        self.assertEqual(status, 404)
        self.assertIn("error", data)
        self.assertEqual(data["path"], "/api/fund/nonexistent")


# ===========================
# Test 8b: файл отсутствует → sentinel {"error":"not found","available":false}
# ===========================
class MissingFileTestCase(unittest.TestCase):
    """Проверяет поведение при отсутствующем файле данных."""

    tmp_dir: tempfile.TemporaryDirectory
    server_thread: threading.Thread
    conn: http.client.HTTPConnection

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.TemporaryDirectory()
        # Пустая папка — ни одного JSON файла
        cls.server_thread = _start_server(cls.tmp_dir.name)
        cls.conn = http.client.HTTPConnection("127.0.0.1", cls.server_thread.port, timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        _stop_server(cls.server_thread)
        cls.tmp_dir.cleanup()

    def test_missing_golive_returns_sentinel(self):
        self.conn.request("GET", "/api/fund/golive")
        resp = self.conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(resp.status, 200)
        self.assertFalse(data.get("available", True))
        self.assertIn("error", data)


# ===========================
# Гейт против рецидива: порт не должен быть константой
# ===========================
class EphemeralPortTestCase(unittest.TestCase):
    """Пин «этот файл параллелится» — карточка `agent-fund-api-tests-bind-a-fixed-port`.

    Проверка ПОВЕДЕНЧЕСКАЯ, а не по тексту: несколько серверов поднимаются ОДНОВРЕМЕННО — ровно
    то, что делают два параллельных pytest'а. Пока порт берёт ядро, все живут; стоит вернуть в
    ``_start_server`` константу — второй ``bind`` падает `OSError: Address already in use`, и тест
    краснеет. Детерминизм здесь обеспечен настоящей одновременностью (сокеты держатся открытыми до
    конца проверки), а НЕ надеждой на то, что ядро не переиспользует только что освобождённый
    порт: такая надежда — это флаки-тест, притворяющийся гейтом.
    """

    SERVERS = 3
    HISTORICAL_CONSTANTS = (18765, 18766)

    def test_concurrent_servers_get_distinct_live_ports(self):
        with tempfile.TemporaryDirectory() as data_dir:
            started = []
            try:
                for _ in range(self.SERVERS):
                    # Каждый следующий поднимается, пока предыдущие ЖИВЫ — условие гонки.
                    started.append(_start_server(data_dir))

                ports = [srv.port for srv in started]
                self.assertEqual(
                    len(set(ports)),
                    len(ports),
                    f"одновременные серверы получили совпадающие порты {ports} — "
                    f"порт снова фиксированный?",
                )
                for port in ports:
                    self.assertGreater(port, 0, "порт 0 не должен доезжать до вызывающего")
                    self.assertNotIn(
                        port,
                        self.HISTORICAL_CONSTANTS,
                        f"порт {port} — старая захардкоженная константа, а не выданный ядром",
                    )

                # Живы именно эти порты: адрес взят у сервера, а не назначен тестом.
                for srv in started:
                    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
                    try:
                        conn.request("GET", "/health")
                        resp = conn.getresponse()
                        body = json.loads(resp.read().decode("utf-8"))
                        self.assertEqual(resp.status, 200)
                        self.assertEqual(body["status"], "ok")
                    finally:
                        conn.close()
            finally:
                for srv in started:
                    _stop_server(srv)

    def test_reported_port_is_the_one_the_socket_is_bound_to(self):
        """`.port` читается у сокета, а не хранится рядом с ним.

        Если кто-то снова начнёт присваивать номер до `bind` (или мимо сервера), эти два значения
        разъедутся.
        """
        with tempfile.TemporaryDirectory() as data_dir:
            srv = _start_server(data_dir)
            try:
                self.assertEqual(srv.port, srv.server.server_address[1])
            finally:
                _stop_server(srv)


if __name__ == "__main__":
    unittest.main(verbosity=2)
