"""Family Fund Investor Cabinet — FastAPI backend.

Лёгкий REST API для инвесторского портала Family Fund. Живёт рядом с
существующим stdlib `http_server.py` (порт 8765) на порту **8766**.

Зависимости: stdlib + FastAPI + Pydantic v2 + bcrypt (для хеширования паролей).
Никаких SQLAlchemy/Redis/python-jose — JWT реализован на stdlib (hmac+hashlib).

Запуск:
    python -m uvicorn spa_core.family_fund.api.app:app --port 8766
или:
    python -m spa_core.family_fund.run_api
"""

__all__ = ["app"]
