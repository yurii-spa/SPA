"""Тесты yield endpoints: /yield/history, /yield/daily."""
from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from .conftest import auth_header


class TestYieldHistoryAuth:
    def test_history_requires_auth(self, client: TestClient):
        assert client.get("/yield/history").status_code == 401

    def test_daily_requires_auth(self, client: TestClient):
        assert client.get("/yield/daily").status_code == 401


class TestYieldHistory:
    def test_history_default(self, client: TestClient, investor_token):
        r = client.get("/yield/history", headers=auth_header(investor_token))
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 3
        assert len(body["days"]) == 3
        assert body["start_date"] == "2026-06-16"
        assert body["end_date"] == "2026-06-18"

    def test_history_chronological(self, client: TestClient, investor_token):
        r = client.get("/yield/history", headers=auth_header(investor_token))
        dates = [d["date"] for d in r.json()["days"]]
        assert dates == sorted(dates)

    def test_history_days_param_limits(self, client: TestClient, investor_token):
        r = client.get("/yield/history?days=1", headers=auth_header(investor_token))
        body = r.json()
        assert body["count"] == 1
        # последний день
        assert body["days"][0]["date"] == "2026-06-18"

    def test_history_total_yield(self, client: TestClient, investor_token):
        r = client.get("/yield/history", headers=auth_header(investor_token))
        total = Decimal(r.json()["total_yield_usd"])
        # 9.5 + 10.0 + 10.8528
        assert total == Decimal("30.3528")

    def test_history_invalid_days_zero(self, client: TestClient, investor_token):
        r = client.get("/yield/history?days=0", headers=auth_header(investor_token))
        assert r.status_code == 422

    def test_history_invalid_days_too_big(self, client: TestClient, investor_token):
        r = client.get("/yield/history?days=999", headers=auth_header(investor_token))
        assert r.status_code == 422

    def test_history_item_fields(self, client: TestClient, investor_token):
        r = client.get("/yield/history", headers=auth_header(investor_token))
        day = r.json()["days"][-1]
        assert day["date"] == "2026-06-18"
        assert day["equity_usd"] == "100010.85"
        assert day["apy_today_pct"] == "3.9609"

    def test_history_readonly_allowed(self, client: TestClient, readonly_token):
        assert client.get(
            "/yield/history", headers=auth_header(readonly_token)
        ).status_code == 200

    def test_history_empty_when_no_data(self, client: TestClient, investor_token, data_dir):
        (data_dir / "equity_curve_daily.json").write_text("{}", encoding="utf-8")
        from spa_core.family_fund.api import file_store

        file_store.invalidate_cache()
        r = client.get("/yield/history", headers=auth_header(investor_token))
        assert r.status_code == 200
        assert r.json()["count"] == 0


class TestYieldDaily:
    def test_daily_latest(self, client: TestClient, investor_token):
        r = client.get("/yield/daily", headers=auth_header(investor_token))
        assert r.status_code == 200
        body = r.json()
        assert body["date"] == "2026-06-18"
        assert body["equity_usd"] == "100010.85"

    def test_daily_specific_date(self, client: TestClient, investor_token):
        r = client.get(
            "/yield/daily?date=2026-06-17", headers=auth_header(investor_token)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["date"] == "2026-06-17"
        assert Decimal(body["equity_usd"]) == Decimal("100005")

    def test_daily_from_report_pnl(self, client: TestClient, investor_token):
        r = client.get(
            "/yield/daily?date=2026-06-18", headers=auth_header(investor_token)
        )
        # daily_pnl_usd из daily_report
        assert r.json()["daily_yield_usd"] == "10.85"

    def test_daily_missing_date_falls_back_to_curve(
        self, client: TestClient, investor_token, data_dir
    ):
        # дата есть в equity curve (2026-06-16), но нет daily_report для неё
        r = client.get(
            "/yield/daily?date=2026-06-16", headers=auth_header(investor_token)
        )
        assert r.status_code == 200
        assert r.json()["date"] == "2026-06-16"

    def test_daily_unknown_date_404(self, client: TestClient, investor_token):
        r = client.get(
            "/yield/daily?date=2020-01-01", headers=auth_header(investor_token)
        )
        assert r.status_code == 404

    def test_daily_bad_date_format_422(self, client: TestClient, investor_token):
        r = client.get(
            "/yield/daily?date=not-a-date", headers=auth_header(investor_token)
        )
        assert r.status_code == 422

    def test_daily_readonly_allowed(self, client: TestClient, readonly_token):
        assert client.get(
            "/yield/daily", headers=auth_header(readonly_token)
        ).status_code == 200
