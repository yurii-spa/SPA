"""Тесты health + portfolio endpoints + RBAC."""
from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from .conftest import auth_header


class TestHealth:
    def test_health_ok(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "timestamp" in body
        assert body["service"] == "family_fund_api"

    def test_health_no_auth_required(self, client: TestClient):
        assert client.get("/health").status_code == 200

    def test_health_has_request_id_header(self, client: TestClient):
        r = client.get("/health")
        assert "X-Request-ID" in r.headers


class TestPortfolioAuth:
    def test_portfolio_requires_auth(self, client: TestClient):
        assert client.get("/portfolio").status_code == 401

    def test_positions_requires_auth(self, client: TestClient):
        assert client.get("/portfolio/positions").status_code == 401

    def test_performance_requires_auth(self, client: TestClient):
        assert client.get("/portfolio/performance").status_code == 401

    def test_invalid_token_rejected(self, client: TestClient):
        r = client.get(
            "/portfolio",
            headers=auth_header("eyJhbGciOiJIUzI1NiJ9.fake.payload"),
        )
        assert r.status_code == 401

    def test_refresh_token_rejected_as_access(self, client: TestClient):
        from spa_core.family_fund.api.auth import create_refresh_token

        rt = create_refresh_token("owner")
        r = client.get("/portfolio", headers=auth_header(rt))
        assert r.status_code == 401


class TestPortfolioRBAC:
    def test_readonly_can_read_portfolio(self, client: TestClient, readonly_token):
        assert client.get(
            "/portfolio", headers=auth_header(readonly_token)
        ).status_code == 200

    def test_investor_can_read(self, client: TestClient, investor_token):
        assert client.get(
            "/portfolio", headers=auth_header(investor_token)
        ).status_code == 200

    def test_admin_can_read(self, client: TestClient, admin_token):
        assert client.get(
            "/portfolio", headers=auth_header(admin_token)
        ).status_code == 200

    def test_owner_can_read(self, client: TestClient, owner_token):
        assert client.get(
            "/portfolio", headers=auth_header(owner_token)
        ).status_code == 200


class TestPortfolioContent:
    def test_portfolio_fields(self, client: TestClient, investor_token):
        r = client.get("/portfolio", headers=auth_header(investor_token))
        assert r.status_code == 200
        body = r.json()
        assert Decimal(body["capital_usd"]) == Decimal("100000")
        assert body["num_positions"] == 5
        assert body["is_demo"] is False
        assert len(body["positions"]) == 5

    def test_positions_sorted_desc(self, client: TestClient, investor_token):
        r = client.get("/portfolio", headers=auth_header(investor_token))
        allocs = [Decimal(p["allocation_usd"]) for p in r.json()["positions"]]
        assert allocs == sorted(allocs, reverse=True)

    def test_position_has_tier(self, client: TestClient, investor_token):
        r = client.get("/portfolio", headers=auth_header(investor_token))
        by_proto = {p["protocol"]: p for p in r.json()["positions"]}
        assert by_proto["aave_v3"]["tier"] == "T1"
        assert by_proto["compound_v3"]["tier"] == "T1"
        assert by_proto["yearn_v3"]["tier"] == "T2"

    def test_weights_sum_to_100(self, client: TestClient, investor_token):
        r = client.get("/portfolio", headers=auth_header(investor_token))
        total = sum(Decimal(p["weight_pct"]) for p in r.json()["positions"])
        assert abs(total - Decimal("100")) < Decimal("0.01")

    def test_largest_position_is_compound(self, client: TestClient, investor_token):
        r = client.get("/portfolio", headers=auth_header(investor_token))
        assert r.json()["positions"][0]["protocol"] == "compound_v3"


class TestPositionsEndpoint:
    def test_positions_list(self, client: TestClient, readonly_token):
        r = client.get("/portfolio/positions", headers=auth_header(readonly_token))
        assert r.status_code == 200
        body = r.json()
        assert body["total_positions"] == 5
        assert len(body["positions"]) == 5

    def test_positions_deployed_sum(self, client: TestClient, investor_token):
        r = client.get("/portfolio/positions", headers=auth_header(investor_token))
        deployed = Decimal(r.json()["deployed_usd"])
        assert deployed > Decimal("90000")


class TestPerformanceEndpoint:
    def test_performance_fields(self, client: TestClient, investor_token):
        r = client.get("/portfolio/performance", headers=auth_header(investor_token))
        assert r.status_code == 200
        body = r.json()
        assert Decimal(body["current_equity"]) == Decimal("100010.85")
        assert body["days_running"] == 30
        assert body["paper_start_date"] == "2026-05-20"
        assert "apy_today_pct" in body

    def test_performance_readonly_allowed(self, client: TestClient, readonly_token):
        assert client.get(
            "/portfolio/performance", headers=auth_header(readonly_token)
        ).status_code == 200


class TestMissingData:
    def test_portfolio_handles_missing_files(self, client: TestClient, investor_token, data_dir):
        # удаляем файлы — endpoint не должен падать с 500
        (data_dir / "current_positions.json").unlink()
        (data_dir / "paper_trading_status.json").unlink()
        from spa_core.family_fund.api import file_store

        file_store.invalidate_cache()
        r = client.get("/portfolio", headers=auth_header(investor_token))
        assert r.status_code == 200
        assert r.json()["num_positions"] == 0
