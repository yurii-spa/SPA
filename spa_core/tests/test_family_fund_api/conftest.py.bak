"""pytest fixtures для Family Fund API.

Использует реальные tmp JSON-файлы (без mocking FS) + tmp users.json.
JWT-секрет задаётся через env var FAMILY_FUND_JWT_SECRET (Keychain fallback).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Гарантируем секрет ДО любого импорта api-модулей.
os.environ.setdefault(
    "FAMILY_FUND_JWT_SECRET", "test-secret-family-fund-32-characters-minimum!!"
)

from fastapi.testclient import TestClient  # noqa: E402

from spa_core.family_fund.api import auth, file_store, middleware  # noqa: E402
from spa_core.family_fund.api import keychain  # noqa: E402
from spa_core.family_fund.api.app import create_app  # noqa: E402
from spa_core.family_fund.api.auth import (  # noqa: E402
    create_access_token,
    hash_password,
)
from spa_core.family_fund.api.models import UserRole  # noqa: E402

# Известные dev-пароли для тестовых юзеров.
TEST_PASSWORDS = {
    "owner": "owner-pw-12345",
    "admin": "admin-pw-12345",
    "investor": "investor-pw-12345",
    "readonly": "readonly-pw-12345",
}


@pytest.fixture(autouse=True)
def _reset_state():
    """Сбрасывает кэши/лимитеры/blacklist между тестами."""
    keychain.reset_cache()
    auth.clear_revoked()
    file_store.invalidate_cache()
    middleware.reset_limiters()
    yield
    auth.clear_revoked()
    middleware.reset_limiters()


@pytest.fixture
def sample_positions() -> dict:
    return {
        "aave_v3": 23750.0,
        "compound_v3": 38000.0,
        "yearn_v3": 11230.28,
        "euler_v2": 9564.55,
        "maple": 12455.16,
    }


@pytest.fixture
def data_dir(tmp_path: Path, sample_positions: dict) -> Path:
    """Создаёт tmp/data с реальными JSON и переключает file_store на него."""
    repo = tmp_path
    data = repo / "data"
    data.mkdir()

    (data / "current_positions.json").write_text(
        json.dumps({
            "is_demo": False,
            "capital_usd": 100000.0,
            "deployed_usd": 94999.99,
            "cash_usd": 5000.01,
            "positions": sample_positions,
        }),
        encoding="utf-8",
    )
    (data / "paper_trading_status.json").write_text(
        json.dumps({
            "is_demo": False,
            "paper_start_date": "2026-05-20",
            "last_cycle_ts": "2026-06-18T20:16:29+00:00",
            "days_running": 30,
            "current_equity": 100010.85,
            "total_return_pct": 0.0109,
            "daily_return_pct": 0.0,
            "apy_today_pct": 3.9609,
            "daily_yield_usd": 10.8528,
            "current_positions": sample_positions,
        }),
        encoding="utf-8",
    )
    (data / "equity_curve_daily.json").write_text(
        json.dumps({
            "summary": {
                "max_drawdown_pct": 0.0,
                "daily_volatility_pct": 0.0,
                "best_day": None,
                "worst_day": None,
            },
            "daily": [
                {
                    "date": "2026-06-16",
                    "close_equity": 100000.0,
                    "equity": 100000.0,
                    "daily_return_pct": 0.0,
                    "apy_today": 3.5,
                    "daily_yield_usd": 9.5,
                },
                {
                    "date": "2026-06-17",
                    "close_equity": 100005.0,
                    "equity": 100005.0,
                    "daily_return_pct": 0.005,
                    "apy_today": 3.8,
                    "daily_yield_usd": 10.0,
                },
                {
                    "date": "2026-06-18",
                    "close_equity": 100010.85,
                    "equity": 100010.85,
                    "daily_return_pct": 0.0,
                    "apy_today": 3.9609,
                    "daily_yield_usd": 10.8528,
                },
            ],
        }),
        encoding="utf-8",
    )
    (data / "daily_report_2026-06-17.json").write_text(
        json.dumps({
            "date": "2026-06-17",
            "is_demo": False,
            "equity_usd": 100005.0,
            "daily_pnl_usd": 10.0,
            "daily_pnl_pct": 0.005,
            "apy_today_pct": 3.8,
        }),
        encoding="utf-8",
    )
    (data / "daily_report_2026-06-18.json").write_text(
        json.dumps({
            "date": "2026-06-18",
            "is_demo": False,
            "equity_usd": 100010.85,
            "daily_pnl_usd": 10.85,
            "daily_pnl_pct": 0.0,
            "apy_today_pct": 3.9609,
        }),
        encoding="utf-8",
    )

    original = file_store._BASE_DIR
    file_store.set_base_dir(repo)
    yield data
    file_store.set_base_dir(original)


@pytest.fixture
def users_file(tmp_path: Path) -> Path:
    """Создаёт tmp users.json и переключает auth-модуль на него."""
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps({
            "users": [
                {
                    "username": "owner",
                    "email": "yuriycooleshov@gmail.com",
                    "role": "owner",
                    "password_hash": hash_password(TEST_PASSWORDS["owner"]),
                },
                {
                    "username": "admin",
                    "email": "admin@earn-defi.com",
                    "role": "admin",
                    "password_hash": hash_password(TEST_PASSWORDS["admin"]),
                },
                {
                    "username": "investor",
                    "email": "investor@earn-defi.com",
                    "role": "investor",
                    "password_hash": hash_password(TEST_PASSWORDS["investor"]),
                },
                {
                    "username": "readonly",
                    "email": "readonly@earn-defi.com",
                    "role": "readonly",
                    "password_hash": hash_password(TEST_PASSWORDS["readonly"]),
                },
            ]
        }),
        encoding="utf-8",
    )
    original = auth._USERS_PATH
    auth.set_users_path(path)
    yield path
    auth.set_users_path(original)


@pytest.fixture
def client(data_dir: Path, users_file: Path) -> TestClient:
    app = create_app()
    # https base_url: иначе httpx не пересылает Secure refresh-cookie
    with TestClient(app, base_url="https://testserver") as c:
        yield c


# ── Tokens ────────────────────────────────────────────────────────────────────
@pytest.fixture
def owner_token() -> str:
    return create_access_token("owner", UserRole.OWNER)


@pytest.fixture
def admin_token() -> str:
    return create_access_token("admin", UserRole.ADMIN)


@pytest.fixture
def investor_token() -> str:
    return create_access_token("investor", UserRole.INVESTOR)


@pytest.fixture
def readonly_token() -> str:
    return create_access_token("readonly", UserRole.READONLY)


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
