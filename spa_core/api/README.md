# SPA API Server — M5

FastAPI REST сервер поверх оркестратора M4.

## Установка

```bash
cd spa_core
pip install fastapi uvicorn[standard] pydantic
```

## Запуск

```bash
cd spa_core
uvicorn api.server:app --reload --port 8000
```

## Endpoints

| Method | Path | Описание |
|--------|------|---------|
| GET | `/health` | Healthcheck |
| GET | `/api/status` | Портфель, позиции, PnL, risk health |
| GET | `/api/protocols` | Whitelist протоколов с последним APY |
| GET | `/api/snapshots` | APY снапшоты (`?limit=50&protocol=key`) |
| GET | `/api/trades` | История сделок (`?open_only=true`) |
| GET | `/api/risk-events` | Risk события (`?severity=HIGH&unresolved_only=true`) |
| GET | `/api/bus/stats` | Статистика Message Bus |
| GET | `/api/bus/messages` | Сообщения шины (`?topic=MARKET_DATA&status=pending`) |
| POST | `/api/run` | Запустить итерацию оркестратора |
| GET | `/api/run/last` | Результат последней итерации |
| GET | `/api/strategy/state` | История состояния для графиков (`?limit=48`) |

## Интерактивная документация

Swagger UI: http://localhost:8000/docs  
ReDoc: http://localhost:8000/redoc
