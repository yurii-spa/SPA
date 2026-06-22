"""
MP-443: Tests for scripts/fund_api_server.py
Запуск: python3 -m pytest tests/test_fund_api.py -v
         -- или --
         python3 -m unittest tests.test_fund_api -v

Используется только stdlib (http.client, unittest, threading, json, tempfile, os).
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

PORT_MAIN = 18765   # основной тест-класс
PORT_MISS = 18766   # тест отсутствующих файлов


def _start_server(data_dir: str, port: int):
    """Запускает сервер в daemon-потоке. Возвращает поток с атрибутом .server."""
    # Переопределяем DATA_DIR модуля для текущего экземпляра
    api_module.DATA_DIR = Path(data_dir)

    server = http.server.HTTPServer(("127.0.0.1", port), api_module.FundAPIHandler)
    server.allow_reuse_address = True

    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.server = server  # сохраняем ссылку для shutdown
    t.start()
    time.sleep(0.3)  # даём серверу подняться
    return t


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
        cls.server_thread = _start_server(data_dir, PORT_MAIN)
        cls.conn = http.client.HTTPConnection("127.0.0.1", PORT_MAIN, timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.server_thread.server.shutdown()
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
        cls.server_thread = _start_server(cls.tmp_dir.name, PORT_MISS)
        cls.conn = http.client.HTTPConnection("127.0.0.1", PORT_MISS, timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        cls.server_thread.server.shutdown()
        cls.tmp_dir.cleanup()

    def test_missing_golive_returns_sentinel(self):
        self.conn.request("GET", "/api/fund/golive")
        resp = self.conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(resp.status, 200)
        self.assertFalse(data.get("available", True))
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
