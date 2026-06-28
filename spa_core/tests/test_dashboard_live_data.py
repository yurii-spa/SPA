"""SPA-V414 / MP-007 — Dashboard: только живые данные.

Статические проверки index.html:
  (a) нет fetch-обращений к удалённым/демо JSON (status.json, protocols.json,
      strategy_state.json и др. — демо-снапшот 2026-05-22);
  (b) присутствуют живые источники (adapter_orchestrator_status, current_positions,
      paper_trading_status, equity_curve_daily, golive_status);
  (c) присутствуют маркеры staleness-баннера (>24h) и day-счётчика трека;
  (d) real_track_start = 2026-06-10.

Только stdlib/unittest, без сети и без pytest.
"""
import os
import re
import unittest

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INDEX_HTML = os.path.join(REPO_ROOT, "index.html")

# RETIRED ARTIFACT: the legacy github.io single-file dashboard (repo-root index.html) was
# retired ON PURPOSE. The canonical dashboard is now the Astro /dashboard page, which fetches
# live data from api.earn-defi.com (/api/v1/golive, /api/v1/evidence, /api/health-public) —
# its honesty is verified by that live-data CONTRACT (see test_track_days_reconciliation and
# the track-record page wiring), not by string-matching this deleted single-file dashboard.
# These SPA-V414/MP-007 source assertions target the deleted file → skipped while it is absent.
if not os.path.isfile(INDEX_HTML):
    pytest.skip(
        "legacy repo-root index.html retired (canonical dashboard is now Astro /dashboard, "
        "verified by its live-data contract); these string-match tests are obsolete",
        allow_module_level=True,
    )

# Демо-файлы (снапшот 2026-05-22), которые дашборд НЕ должен читать.
# Префикс «'/» или «"/» исключает ложное срабатывание на risk_alerts.json и т.п.
FORBIDDEN_DEMO_SOURCES = [
    "status.json",
    "protocols.json",
    "strategy_state.json",
    "strategy_v2.json",
    "backtest_results.json",
    "alerts.json",
    "latest_report.json",
    "optimization_recommendations.json",
    "decision_log.json",
    "bus_stats.json",
    "portfolio_status.json",
]

# Живые источники реального трека (cycle_runner / adapter_orchestrator).
REQUIRED_LIVE_SOURCES = [
    "adapter_orchestrator_status.json",
    "current_positions.json",
    "paper_trading_status.json",
    "equity_curve_daily.json",
    "golive_status.json",
    "risk_alerts.json",
]


def _fetch_targets(html):
    """Все имена JSON-файлов, которые index.html реально фетчит: '/<name>.json."""
    return set(re.findall(r"""['"]/([A-Za-z0-9_.-]+\.json)""", html))


class TestDashboardLiveData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue_ = True
        with open(INDEX_HTML, encoding="utf-8") as f:
            cls.html = f.read()
        cls.targets = _fetch_targets(cls.html)

    # (a) демо-источники не читаются
    def test_no_forbidden_demo_sources_fetched(self):
        for name in FORBIDDEN_DEMO_SOURCES:
            with self.subTest(source=name):
                self.assertNotIn(
                    name, self.targets,
                    f"index.html всё ещё обращается к демо-файлу {name}",
                )

    def test_no_fetch_call_to_status_or_protocols(self):
        # Прямая проверка fetch-вызовов на два файла из формулировки MP-007.
        self.assertIsNone(
            re.search(r"""fetch\([^)]*['"]/(status|protocols)\.json""", self.html),
            "найден fetch(...'/status.json' | '/protocols.json')",
        )

    # (b) живые источники присутствуют
    def test_live_sources_fetched(self):
        for name in REQUIRED_LIVE_SOURCES:
            with self.subTest(source=name):
                self.assertIn(
                    name, self.targets,
                    f"index.html не читает живой источник {name}",
                )

    # (c) staleness-баннер и day-счётчик
    def test_staleness_banner_markers(self):
        self.assertIn("renderStalenessBanner", self.html)
        self.assertIn("staleness-banner", self.html)
        self.assertIn("Данные устарели", self.html)

    def test_track_day_counter_markers(self):
        self.assertIn("realTrackDay", self.html)
        self.assertIn("track-day-counter", self.html)

    # (d) реальный старт трека
    def test_real_track_start_constant(self):
        self.assertIsNotNone(
            re.search(r"REAL_TRACK_START\s*=\s*'2026-06-10'", self.html),
            "REAL_TRACK_START = '2026-06-10' не найден",
        )

    def test_real_track_start_declared_once(self):
        decls = re.findall(r"const\s+REAL_TRACK_START\s*=", self.html)
        self.assertEqual(len(decls), 1, "REAL_TRACK_START должен объявляться ровно один раз")

    # Адаптеры живого статуса присутствуют и используются
    def test_live_status_builders_present_and_used(self):
        for fn in ("buildLiveStatus", "mapOrchToProtocols"):
            with self.subTest(fn=fn):
                # объявление + хотя бы один вызов
                self.assertIsNotNone(re.search(rf"function {fn}\(", self.html))
                self.assertGreaterEqual(
                    len(re.findall(rf"{fn}\(", self.html)), 2,
                    f"{fn} объявлен, но не вызывается",
                )

    # Честность: нет хардкода дня трека
    def test_day_counter_not_hardcoded(self):
        self.assertIsNone(
            re.search(r"День\s+\d+\s+реального трека", self.html),
            "день трека захардкожен — должен вычисляться в JS",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
